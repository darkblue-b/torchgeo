# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import os
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import pytest
import torch
import torch.nn as nn
from pyproj import CRS

from torchgeo.datasets import (
    PRISMA,
    DatasetNotFoundError,
    IntersectionDataset,
    UnionDataset,
)


class TestPRISMA:
    @pytest.fixture
    def dataset(self) -> PRISMA:
        paths = os.path.join('tests', 'data', 'prisma')
        transforms = nn.Identity()
        return PRISMA(paths, transforms=transforms)

    def test_len(self, dataset: PRISMA) -> None:
        assert len(dataset) == 4

    def test_getitem(self, dataset: PRISMA) -> None:
        x = dataset[dataset.bounds]
        assert isinstance(x, dict)
        assert isinstance(x['crs'], CRS)
        assert isinstance(x['image'], torch.Tensor)

    def test_and(self, dataset: PRISMA) -> None:
        ds = dataset & dataset
        assert isinstance(ds, IntersectionDataset)

    def test_or(self, dataset: PRISMA) -> None:
        ds = dataset | dataset
        assert isinstance(ds, UnionDataset)

    def test_plot(self, dataset: PRISMA) -> None:
        x = dataset[dataset.bounds]
        dataset.plot(x, suptitle='Test')
        plt.close()

    def test_no_data(self, tmp_path: Path) -> None:
        with pytest.raises(DatasetNotFoundError, match='Dataset not found'):
            PRISMA(tmp_path)

    def test_invalid_query(self, dataset: PRISMA) -> None:
        with pytest.raises(
            IndexError, match='query: .* not found in index with bounds:'
        ):
            dataset[0:0, 0:0, pd.Timestamp.min : pd.Timestamp.min]
