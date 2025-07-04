# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""AgriFieldNet India Challenge dataset."""

import os
import re
from collections.abc import Callable, Iterable, Sequence
from typing import Any, ClassVar

import matplotlib.pyplot as plt
import pandas as pd
import torch
from matplotlib.figure import Figure
from pyproj import CRS
from torch import Tensor

from .errors import DatasetNotFoundError, RGBBandsMissingError
from .geo import RasterDataset
from .utils import GeoSlice, Path, which


class AgriFieldNet(RasterDataset):
    """AgriFieldNet India Challenge dataset.

    The `AgriFieldNet India Challenge
    <https://zindi.africa/competitions/agrifieldnet-india-challenge>`__ dataset
    includes satellite imagery from Sentinel-2 cloud free composites
    (single snapshot) and labels for crop type that were collected by ground survey.
    The Sentinel-2 data are then matched with corresponding labels.
    The dataset contains 7081 fields, which have been split into training and
    test sets (5551 fields in the train and 1530 fields in the test).
    Satellite imagery and labels are tiled into 256x256 chips adding up to 1217 tiles.
    The fields are distributed across all chips, some chips may only have train or
    test fields and some may have both. Since the labels are derived from data
    collected on the ground, not all the pixels are labeled in each chip.
    If the field ID for a pixel is set to 0 it means that pixel is not included in
    either of the train or test set (and correspondingly the crop label
    will be 0 as well). For this challenge train and test sets have slightly
    different crop type distributions. The train set follows the distribution
    of ground reference data which is a skewed distribution with a few dominant
    crops being over represented. The test set was drawn randomly from an area
    weighted field list that ensured that fields with less common crop types
    were better represented in the test set. The original dataset can be
    downloaded from `Source Cooperative <https://beta.source.coop/
    radiantearth/agrifieldnet-competition/>`__.

    Dataset format:

    * images are 12-band Sentinel-2 data
    * masks are tiff images with unique values representing the class and field id

    Dataset classes:

    * 0. No-Data
    * 1. Wheat
    * 2. Mustard
    * 3. Lentil
    * 4. No Crop/Fallow
    * 5. Green pea
    * 6. Sugarcane
    * 8. Garlic
    * 9. Maize
    * 13. Gram
    * 14. Coriander
    * 15. Potato
    * 16. Berseem
    * 36. Rice

    If you use this dataset in your research, please cite the following dataset:

    * https://doi.org/10.34911/rdnt.wu92p1

    .. note::

       This dataset requires the following additional library to be installed:

       * `azcopy <https://github.com/Azure/azure-storage-azcopy>`_: to download the
         dataset from Source Cooperative.

    .. versionadded:: 0.6
    """

    url = 'https://radiantearth.blob.core.windows.net/mlhub/ref_agrifieldnet_competition_v1'

    filename_glob = 'ref_agrifieldnet_competition_v1_source_*_{}_10m.*'
    filename_regex = r"""
        ^ref_agrifieldnet_competition_v1_source_
        (?P<unique_folder_id>[a-z0-9]{5})
        _(?P<band>B[0-9A-Z]{2})_10m
    """

    rgb_bands = ('B04', 'B03', 'B02')
    all_bands = (
        'B01',
        'B02',
        'B03',
        'B04',
        'B05',
        'B06',
        'B07',
        'B08',
        'B8A',
        'B09',
        'B11',
        'B12',
    )

    cmap: ClassVar[dict[int, tuple[int, int, int, int]]] = {
        0: (0, 0, 0, 255),
        1: (255, 211, 0, 255),
        2: (255, 37, 37, 255),
        3: (0, 168, 226, 255),
        4: (255, 158, 9, 255),
        5: (37, 111, 0, 255),
        6: (255, 255, 0, 255),
        8: (111, 166, 0, 255),
        9: (0, 175, 73, 255),
        13: (222, 166, 9, 255),
        14: (222, 166, 9, 255),
        15: (124, 211, 255, 255),
        16: (226, 0, 124, 255),
        36: (137, 96, 83, 255),
    }

    def __init__(
        self,
        paths: Path | Iterable[Path] = 'data',
        crs: CRS | None = None,
        classes: list[int] = list(cmap.keys()),
        bands: Sequence[str] = all_bands,
        transforms: Callable[[dict[str, Tensor]], dict[str, Tensor]] | None = None,
        cache: bool = True,
        download: bool = False,
    ) -> None:
        """Initialize a new AgriFieldNet dataset instance.

        Args:
            paths: one or more root directories to search for files to load
            crs: :term:`coordinate reference system (CRS)` to warp to
                (defaults to the CRS of the first file found)
            classes: list of classes to include, the rest will be mapped to 0
                (defaults to all classes)
            bands: the subset of bands to load
            transforms: a function/transform that takes input sample and its target as
                entry and returns a transformed version
            cache: if True, cache the dataset in memory
            download: if True, download dataset and store it in the root directory

        Raises:
            DatasetNotFoundError: If dataset is not found and *download* is False.
        """
        assert set(classes) <= self.cmap.keys(), (
            f'Only the following classes are valid: {list(self.cmap.keys())}.'
        )
        assert 0 in classes, 'Classes must include the background class: 0'

        self.paths = paths
        self.download = download
        self.filename_glob = self.filename_glob.format(bands[0])

        self._verify()

        super().__init__(
            paths=paths, crs=crs, bands=bands, transforms=transforms, cache=cache
        )

        # Map chosen classes to ordinal numbers, all others mapped to background class
        self.ordinal_map = torch.zeros(max(self.cmap.keys()) + 1, dtype=self.dtype)
        self.ordinal_cmap = torch.zeros((len(classes), 4), dtype=torch.uint8)
        for v, k in enumerate(classes):
            self.ordinal_map[k] = v
            self.ordinal_cmap[v] = torch.tensor(self.cmap[k])

    def __getitem__(self, query: GeoSlice) -> dict[str, Any]:
        """Retrieve input, target, and/or metadata indexed by spatiotemporal slice.

        Args:
            query: [xmin:xmax:xres, ymin:ymax:yres, tmin:tmax:tres] coordinates to index.

        Returns:
            Sample of input, target, and/or metadata at that index.

        Raises:
            IndexError: If *query* is not found in the index.
        """
        assert isinstance(self.paths, str | os.PathLike)

        x, y, t = self._disambiguate_slice(query)
        interval = pd.Interval(t.start, t.stop)
        index = self.index.iloc[self.index.index.overlaps(interval)]
        index = index.iloc[:: t.step]
        index = index.cx[x.start : x.stop, y.start : y.stop]

        if index.empty:
            raise IndexError(
                f'query: {query} not found in index with bounds: {self.bounds}'
            )

        data_list: list[Tensor] = []
        filename_regex = re.compile(self.filename_regex, re.VERBOSE)
        for band in self.bands:
            band_filepaths = []
            for filepath in index.filepath:
                filename = os.path.basename(filepath)
                directory = os.path.dirname(filepath)
                match = re.match(filename_regex, filename)
                if match:
                    if 'band' in match.groupdict():
                        start = match.start('band')
                        end = match.end('band')
                        filename = filename[:start] + band + filename[end:]
                filepath = os.path.join(directory, filename)
                band_filepaths.append(filepath)
            data_list.append(self._merge_files(band_filepaths, query))
        image = torch.cat(data_list)

        mask_filepaths = []
        for root, dirs, files in os.walk(os.path.join(self.paths, 'train_labels')):
            for file in files:
                if not file.endswith('_field_ids.tif') and file.endswith('.tif'):
                    file_path = os.path.join(root, file)
                    mask_filepaths.append(file_path)

        mask = self._merge_files(mask_filepaths, query)
        mask = self.ordinal_map[mask.squeeze().long()]

        sample = {
            'crs': self.crs,
            'bounds': query,
            'image': image.float(),
            'mask': mask.long(),
        }

        if self.transforms is not None:
            sample = self.transforms(sample)

        return sample

    def _verify(self) -> None:
        """Verify the integrity of the dataset."""
        # Check if the files already exist
        if self.files:
            return

        # Check if the user requested to download the dataset
        if not self.download:
            raise DatasetNotFoundError(self)

        # Download the dataset
        self._download()

    def _download(self) -> None:
        """Download the dataset."""
        assert isinstance(self.paths, str | os.PathLike)
        os.makedirs(self.paths, exist_ok=True)
        azcopy = which('azcopy')
        azcopy('sync', f'{self.url}', self.paths, '--recursive=true')

    def plot(
        self,
        sample: dict[str, Tensor],
        show_titles: bool = True,
        suptitle: str | None = None,
    ) -> Figure:
        """Plot a sample from the dataset.

        Args:
            sample: a sample returned by :meth:`__getitem__`
            show_titles: flag indicating whether to show titles above each panel
            suptitle: optional string to use as a suptitle

        Returns:
            a matplotlib Figure with the rendered sample

        Raises:
            RGBBandsMissingError: If *bands* does not include all RGB bands.
        """
        rgb_indices = []
        for band in self.rgb_bands:
            if band in self.bands:
                rgb_indices.append(self.bands.index(band))
            else:
                raise RGBBandsMissingError()

        image = sample['image'][rgb_indices].permute(1, 2, 0)
        image = (image - image.min()) / (image.max() - image.min())

        mask = sample['mask'].squeeze()
        ncols = 2

        showing_prediction = 'prediction' in sample
        if showing_prediction:
            pred = sample['prediction'].squeeze()
            ncols += 1

        fig, axs = plt.subplots(nrows=1, ncols=ncols, figsize=(ncols * 4, 4))
        axs[0].imshow(image)
        axs[0].axis('off')
        axs[1].imshow(self.ordinal_cmap[mask], interpolation='none')
        axs[1].axis('off')
        if show_titles:
            axs[0].set_title('Image')
            axs[1].set_title('Mask')

        if showing_prediction:
            axs[2].imshow(self.ordinal_cmap[pred], interpolation='none')
            axs[2].axis('off')
            if show_titles:
                axs[2].set_title('Prediction')

        if suptitle is not None:
            plt.suptitle(suptitle)

        return fig
