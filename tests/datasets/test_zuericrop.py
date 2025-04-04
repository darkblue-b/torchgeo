# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import os
from pathlib import Path

import matplotlib.pyplot as plt
import pytest
import torch
import torch.nn as nn
from pytest import MonkeyPatch

from torchgeo.datasets import DatasetNotFoundError, RGBBandsMissingError, ZueriCrop

pytest.importorskip('h5py', minversion='3.8')


class TestZueriCrop:
    @pytest.fixture
    def dataset(self, monkeypatch: MonkeyPatch, tmp_path: Path) -> ZueriCrop:
        url = os.path.join('tests', 'data', 'zuericrop') + os.sep
        monkeypatch.setattr(ZueriCrop, 'url', url)
        root = tmp_path
        transforms = nn.Identity()
        return ZueriCrop(root=root, transforms=transforms, download=True)

    def test_getitem(self, dataset: ZueriCrop) -> None:
        x = dataset[0]
        assert isinstance(x, dict)
        assert isinstance(x['image'], torch.Tensor)
        assert isinstance(x['mask'], torch.Tensor)
        assert isinstance(x['bbox_xyxy'], torch.Tensor)
        assert isinstance(x['label'], torch.Tensor)

        # Image tests
        assert x['image'].ndim == 4

        # Instance masks tests
        assert x['mask'].ndim == 3
        assert x['mask'].shape[-2:] == x['image'].shape[-2:]

        # Bboxes tests
        assert x['bbox_xyxy'].ndim == 2
        assert x['bbox_xyxy'].shape[1] == 4

        # Labels tests
        assert x['label'].ndim == 1

    def test_len(self, dataset: ZueriCrop) -> None:
        assert len(dataset) == 2

    def test_already_downloaded(self, dataset: ZueriCrop) -> None:
        ZueriCrop(root=dataset.root, download=True)

    def test_not_downloaded(self, tmp_path: Path) -> None:
        with pytest.raises(DatasetNotFoundError, match='Dataset not found'):
            ZueriCrop(tmp_path)

    def test_invalid_bands(self) -> None:
        with pytest.raises(ValueError):
            ZueriCrop(bands=('OK', 'BK'))

    def test_plot(self, dataset: ZueriCrop) -> None:
        dataset.plot(dataset[0], suptitle='Test')
        plt.close()

        sample = dataset[0]
        sample['prediction'] = sample['mask'].clone()
        dataset.plot(sample, suptitle='prediction')
        plt.close()

    def test_plot_rgb(self, dataset: ZueriCrop) -> None:
        dataset = ZueriCrop(root=dataset.root, bands=('B02',))
        with pytest.raises(
            RGBBandsMissingError, match='Dataset does not contain some of the RGB bands'
        ):
            dataset.plot(dataset[0], time_step=0, suptitle='Single Band')
