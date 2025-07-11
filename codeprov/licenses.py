import importlib.resources

from dataclasses import dataclass
from functools import cache
from marisa_trie import Trie


FOSS_LICENSE_CATEGORIES = {
    'Copyleft',
    'Copyleft Limited',
    'Patent License',
    'Permissive',
    'Public Domain',
    'CLA',
}

OTHER_LICENSE_CATEGORIES = {
    'Commercial',
    'Proprietary Free',
    'Free Restricted',
    'Source-available',
    'Unstated License',
}

LICENSE_CATEGORIES = FOSS_LICENSE_CATEGORIES | OTHER_LICENSE_CATEGORIES


@dataclass(slots=True)
class License:
    id: int
    spdx_key: str
    short_name: str
    category: str


class LicensesTrie:
    def __init__(self, *args, **kwargs):
        self.trie = Trie(*args, **kwargs)

    def load(self, path: str, mmap=True):
        self.trie = (self.trie.mmap if mmap else self.trie.load)(path)
        return self

    def get_license(self, spdx_key: str):
        key = spdx_key + '\1'
        item: tuple[str, int] | None = next(self.trie.iteritems(key), None)  # type: ignore

        if item is not None:
            row, row_id = item
            spdx_key, short_name, category, *others = row.split('\1')
            return License(row_id, spdx_key, short_name, category)

    def get_license_by_id(self, id: int):
        try:
            row = self.trie.restore_key(id)
        except KeyError:
            return None

        spdx_key, short_name, category, *others = row.split('\1')
        return License(id, spdx_key, short_name, category)


@cache
def builtin_licenses_trie() -> LicensesTrie:
    file = importlib.resources.files('codeprov').joinpath('licenses.marisa').open('rb')
    trie = LicensesTrie()
    trie.trie.frombytes(file.read())
    return trie
