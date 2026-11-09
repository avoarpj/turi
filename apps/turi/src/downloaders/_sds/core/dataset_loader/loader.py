from os import listdir
from apps.turi.src.downloaders._sds.core.PARAMS import DATASETS_CONF_PATH
from apps.turi.src.downloaders._sds.core.dataset_meta.dataset import ReadDatasetMeta, DatasetMeta

def get_datasets(debug: bool = False) -> list[DatasetMeta]:
    datasets_folders = listdir(DATASETS_CONF_PATH)
    datasets: list[DatasetMeta] = []

    for folder in datasets_folders:
        full_path = DATASETS_CONF_PATH / folder

        dataset = ReadDatasetMeta(full_path)
        datasets.append(dataset)

    if debug is True:
        print(f"{len(datasets_folders)} folders in datasets")
        print(f"{len(datasets)} datasets loaded")

    return datasets
