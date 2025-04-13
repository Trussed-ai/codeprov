import os
import json

from typing import TypedDict
from dataclasses import dataclass, asdict


CODEPROV_HOME = os.path.expanduser(
    os.getenv(
        'CODEPROV_HOME',
        os.path.join(os.getenv('XDG_CACHE_HOME', '~/.cache'), 'codeprov'),
    )
)


@dataclass
class Manifest:
    language: str
    parser: str
    sample: str

    @property
    def name(self):
        return f'{self.language}_{self.parser}_{self.sample}'.lower()


class Metadata:
    def __init__(self, name: str):
        self.name = name

        if os.path.exists(os.path.abspath(name)):
            self.path = os.path.abspath(name)
        else:
            self.path = os.path.join(CODEPROV_HOME, self.name)

        self.manifest_path = os.path.join(self.path, 'manifest.json')
        self.digests_db_path = os.path.join(self.path, 'digests')
        self.digests_bloom_path = os.path.join(self.path, 'digests.bloom')
        self.digests_trie_path = os.path.join(self.path, 'digests.marisa')
        self.sources_trie_path = os.path.join(self.path, 'sources.marisa')

    def __repr__(self):
        return f'<{type(self).__name__}: {self.path}>'

    def load_manifest(self) -> Manifest:
        return Manifest(**json.load(open(self.manifest_path)))
    
    def save_manifest(self, manifest: Manifest):
        json.dump(asdict(manifest), open(self.manifest_path, 'w'), indent=4)

