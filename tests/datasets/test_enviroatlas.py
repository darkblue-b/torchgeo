# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import os
import shutil
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import pytest
import torch
import torch.nn as nn
from _pytest.fixtures import SubRequest
from pyproj import CRS
from pytest import MonkeyPatch

from torchgeo.datasets import (
    DatasetNotFoundError,
    EnviroAtlas,
    IntersectionDataset,
    UnionDataset,
)


class TestEnviroAtlas:
    @pytest.fixture(
        params=[
            (('naip', 'prior', 'lc'), False),
            (('naip', 'prior', 'buildings', 'lc'), True),
            (('naip', 'prior'), False),
        ]
    )
    def dataset(
        self, request: SubRequest, monkeypatch: MonkeyPatch, tmp_path: Path
    ) -> EnviroAtlas:
        monkeypatch.setattr(EnviroAtlas, 'md5', '071ec65c611e1d4915a5247bffb5ad87')
        monkeypatch.setattr(
            EnviroAtlas,
            'url',
            os.path.join('tests', 'data', 'enviroatlas', 'enviroatlas_lotp.zip'),
        )
        monkeypatch.setattr(
            EnviroAtlas,
            '_files',
            ['pittsburgh_pa-2010_1m-train_tiles-debuffered', 'spatial_index.geojson'],
        )
        root = tmp_path
        transforms = nn.Identity()
        return EnviroAtlas(
            root,
            layers=request.param[0],
            transforms=transforms,
            prior_as_input=request.param[1],
            download=True,
            checksum=True,
        )

    def test_getitem(self, dataset: EnviroAtlas) -> None:
        x = dataset[dataset.bounds]
        assert isinstance(x, dict)
        assert isinstance(x['crs'], CRS)
        assert isinstance(x['mask'], torch.Tensor)

    def test_len(self, dataset: EnviroAtlas) -> None:
        assert len(dataset) == 1

    def test_and(self, dataset: EnviroAtlas) -> None:
        ds = dataset & dataset
        assert isinstance(ds, IntersectionDataset)

    def test_or(self, dataset: EnviroAtlas) -> None:
        ds = dataset | dataset
        assert isinstance(ds, UnionDataset)

    def test_already_extracted(self, dataset: EnviroAtlas) -> None:
        EnviroAtlas(root=dataset.root, download=True)

    def test_already_downloaded(self, tmp_path: Path) -> None:
        root = tmp_path
        shutil.copy(
            os.path.join('tests', 'data', 'enviroatlas', 'enviroatlas_lotp.zip'), root
        )
        EnviroAtlas(root)

    def test_not_downloaded(self, tmp_path: Path) -> None:
        with pytest.raises(DatasetNotFoundError, match='Dataset not found'):
            EnviroAtlas(tmp_path, checksum=True)

    def test_out_of_bounds_query(self, dataset: EnviroAtlas) -> None:
        with pytest.raises(
            IndexError, match='query: .* not found in index with bounds:'
        ):
            dataset[0:0, 0:0, pd.Timestamp.min : pd.Timestamp.min]

    def test_multiple_hits_query(self, dataset: EnviroAtlas) -> None:
        ds = EnviroAtlas(
            root=dataset.root,
            splits=['pittsburgh_pa-2010_1m-train', 'austin_tx-2012_1m-test'],
            layers=dataset.layers,
        )
        with pytest.raises(
            IndexError, match='query: .* spans multiple tiles which is not valid'
        ):
            ds[dataset.bounds]

    def test_plot(self, dataset: EnviroAtlas) -> None:
        x = dataset[dataset.bounds]
        if 'naip' not in dataset.layers or 'lc' not in dataset.layers:
            with pytest.raises(ValueError, match="The 'naip' and"):
                dataset.plot(x)
        else:
            dataset.plot(x, suptitle='Test')
            plt.close()
            dataset.plot(x, show_titles=False)
            plt.close()
            x['prediction'] = x['mask'][0].clone()
            dataset.plot(x)
            plt.close()
