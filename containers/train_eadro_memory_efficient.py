#!/usr/bin/env python3
"""Train Eadro with upstream balancing semantics and bounded peak memory."""

from __future__ import annotations

import argparse
import gc
import glob
import pickle
import random
from collections import Counter, defaultdict
from pathlib import Path

import dgl
import numpy as np
import src.eadro.handlers as handlers
import torch
from loguru import logger
from src.preprocessing.base import DatasetMetadata
from torch.utils.data import Dataset


def compact_sample(sample):
    sample.log = np.asarray(sample.log, dtype=np.float32)
    sample.trace = np.asarray(sample.trace, dtype=np.float32)
    sample.metric = np.asarray(sample.metric, dtype=np.float32)
    return sample


class LazyChunkDataset(Dataset):
    """Create graph tensors on access instead of duplicating them in memory."""

    def __init__(self, samples, metadata: DatasetMetadata):
        self.samples = samples
        self.metadata = metadata
        self.node_num = len(metadata.services)
        sources = [edge[0] for edge in metadata.service_calling_edges]
        targets = [edge[1] for edge in metadata.service_calling_edges]
        if not sources:
            raise ValueError("metadata contains no service calling edges")
        self.edges = (sources, targets)
        self.labels = [
            sample.get_gt_service_id(metadata.service_name_to_id) for sample in samples
        ]
        logger.info(f"lazy dataset initialized with {len(samples)} samples")
        logger.info(f"label distribution: {dict(Counter(self.labels))}")

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, index):
        sample = self.samples[index]
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
        return graph, self.labels[index]


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
    selected = defaultdict(list)
    for batch_file in train_files:
        with open(batch_file, "rb") as handle:
            batch = pickle.load(handle)
        for sample in batch:
            label = sample.get_gt_service_id(metadata.service_name_to_id)
            if cap is None or len(selected[label]) < cap:
                selected[label].append(compact_sample(sample))
        del batch
        gc.collect()
    train_samples = [sample for samples in selected.values() for sample in samples]

    test_samples = []
    for batch_file in test_files:
        with open(batch_file, "rb") as handle:
            batch = pickle.load(handle)
        test_samples.extend(compact_sample(sample) for sample in batch)
        del batch
        gc.collect()

    random.shuffle(train_samples)
    random.shuffle(test_samples)
    return train_samples, test_samples, metadata


handlers.ChunkDataset = LazyChunkDataset
handlers.EadroDataHandler.load_data = load_data_streaming

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

