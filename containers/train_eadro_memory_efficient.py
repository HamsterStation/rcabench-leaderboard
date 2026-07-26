#!/usr/bin/env python3
"""Train Eadro with upstream balancing semantics and bounded peak memory."""

from __future__ import annotations

import argparse
import gc
import glob
import pickle
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import dgl
import numpy as np
import src.eadro.handlers as handlers
import torch
from loguru import logger
from src.exp.config import Config
from src.preprocessing.base import DatasetMetadata
from torch.utils.data import DataLoader, Dataset


@dataclass(frozen=True)
class SampleRef:
    batch_file: str
    index: int
    label: int


class DiskBackedChunkDataset(Dataset):
    """Load one preprocessing batch at a time instead of retaining 119 GB in RAM."""

    def __init__(self, samples: list[SampleRef], metadata: DatasetMetadata):
        self.samples = samples
        self.metadata = metadata
        self.node_num = len(metadata.services)
        sources = [edge[0] for edge in metadata.service_calling_edges]
        targets = [edge[1] for edge in metadata.service_calling_edges]
        if not sources:
            raise ValueError("metadata contains no service calling edges")
        self.edges = (sources, targets)
        self.cached_path: str | None = None
        self.cached_batch = None
        logger.info(f"disk-backed dataset initialized with {len(samples)} samples")
        logger.info(f"label distribution: {dict(Counter(ref.label for ref in samples))}")

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, index):
        ref = self.samples[index]
        if ref.batch_file != self.cached_path:
            with open(ref.batch_file, "rb") as handle:
                self.cached_batch = pickle.load(handle)
            self.cached_path = ref.batch_file
        sample = self.cached_batch[ref.index]
        graph = dgl.graph(self.edges, num_nodes=self.node_num)
        graph.ndata["logs"] = torch.as_tensor(
            np.nan_to_num(np.asarray(sample.log), nan=0.0, posinf=0.0, neginf=0.0),
            dtype=torch.float32,
        )
        graph.ndata["metrics"] = torch.as_tensor(
            np.nan_to_num(np.asarray(sample.metric), nan=0.0, posinf=0.0, neginf=0.0),
            dtype=torch.float32,
        )
        graph.ndata["traces"] = torch.as_tensor(
            np.nan_to_num(np.asarray(sample.trace), nan=0.0, posinf=0.0, neginf=0.0),
            dtype=torch.float32,
        )
        return graph, ref.label


def create_bounded_data_loaders(self, train_samples, test_samples, metadata, config):
    """Keep file locality and bound each CPU batch to a safe size."""
    train_dataset = DiskBackedChunkDataset(train_samples, metadata)
    test_dataset = DiskBackedChunkDataset(test_samples, metadata)
    batch_size = min(int(config.get("training.batch_size")), 16)
    logger.info(f"using bounded batch_size={batch_size} with sequential disk access")
    self.metadata = metadata
    self.train_loader = DataLoader(
        train_dataset,
        batch_size=batch_size,
        shuffle=False,
        collate_fn=handlers.collate_fn,
        pin_memory=False,
    )
    self.test_loader = DataLoader(
        test_dataset,
        batch_size=batch_size,
        shuffle=False,
        collate_fn=handlers.collate_fn,
        pin_memory=False,
    )
    return self.train_loader, self.test_loader


def load_data_streaming(
    self,
    config,
    dataset_folder: str,
    train_split: str = "train",
    test_split: str = "test",
    test_dataset_folder: str | None = None,
):
    dataset_name = config.get("dataset")
    actual_test_folder = test_dataset_folder or dataset_folder
    train_files = sorted(
        glob.glob(f".cache/{dataset_name}_{dataset_folder}_{train_split}_samples_batch_*.pkl")
    )
    test_files = sorted(
        glob.glob(
            f".cache/{dataset_name}_{actual_test_folder}_{test_split}_samples_batch_*.pkl"
        )
    )
    metadata_path = Path(f".cache/{dataset_name}_{dataset_folder}_train_metadata.pkl")
    metadata = DatasetMetadata.from_pkl(str(metadata_path))
    if metadata is None:
        raise FileNotFoundError(f"metadata is missing: {metadata_path}")
    if not train_files or not test_files:
        raise FileNotFoundError(
            f"missing cache batches: train={len(train_files)} test={len(test_files)}"
        )

    counts = Counter()
    for batch_file in train_files:
        with open(batch_file, "rb") as handle:
            batch = pickle.load(handle)
        counts.update(sample.get_gt_service_id(metadata.service_name_to_id) for sample in batch)
        del batch
        gc.collect()

    cap = min(counts.values()) * 20 if config.get("training.balance_train_set") else None
    logger.info(f"upstream cap per label={cap}; original counts={dict(counts)}")
    selected_counts = defaultdict(int)
    train_samples: list[SampleRef] = []
    for batch_file in train_files:
        with open(batch_file, "rb") as handle:
            batch = pickle.load(handle)
        for index, sample in enumerate(batch):
            label = sample.get_gt_service_id(metadata.service_name_to_id)
            if cap is None or selected_counts[label] < cap:
                train_samples.append(SampleRef(batch_file, index, label))
                selected_counts[label] += 1
        del batch
        gc.collect()

    test_samples: list[SampleRef] = []
    for batch_file in test_files:
        with open(batch_file, "rb") as handle:
            batch = pickle.load(handle)
        test_samples.extend(
            SampleRef(
                batch_file,
                index,
                sample.get_gt_service_id(metadata.service_name_to_id),
            )
            for index, sample in enumerate(batch)
        )
        del batch
        gc.collect()

    logger.info(
        f"selected disk references: train={len(train_samples)} test={len(test_samples)}"
    )
    return train_samples, test_samples, metadata


handlers.ChunkDataset = DiskBackedChunkDataset
handlers.EadroDataHandler.load_data = load_data_streaming
handlers.EadroDataHandler.create_data_loaders = create_bounded_data_loaders

original_config_get = Config.get


def bounded_config_get(self, key):
    # OPS-Lite runs on a 15 GiB CPU server; validate every epoch and retain the best of 10.
    overrides = {
        "training.epochs": 10,
        "training.evaluation_epoch": 1,
        "training.patience": 3,
    }
    if key in overrides:
        return overrides[key]
    return original_config_get(self, key)


Config.get = bounded_config_get

from client import train  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="settings.toml")
    parser.add_argument("--dataset-folder", required=True)
    parser.add_argument("--test-dataset-folder", required=True)
    parser.add_argument("--experiment-name", required=True)
    args = parser.parse_args()
    train(
        config_file=args.config,
        dataset_folder=args.dataset_folder,
        test_dataset_folder=args.test_dataset_folder,
        experiment_name=args.experiment_name,
    )


if __name__ == "__main__":
    main()
