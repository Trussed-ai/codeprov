import os
import json

from typing import TypedDict


CODEPROV_HOME = os.path.expanduser(
    os.getenv(
        'CODEPROV_HOME',
        os.path.join(os.getenv('XDG_CACHE_HOME', '~/.cache'), 'codeprov'),
    )
)


class Manifest(TypedDict):
    language: str
    parser: str


class Metadata:
    def __init__(self, name: str):
        self.name = name
        self.path = os.path.join(CODEPROV_HOME, self.name)

        self.manifest_path = os.path.join(self.path, 'manifest.json')
        self.digests_db_path = os.path.join(self.path, 'digests')
        self.digests_bloom_path = os.path.join(self.path, 'digests.bloom')
        self.digests_trie_path = os.path.join(self.path, 'digests.marisa')
        self.sources_trie_path = os.path.join(self.path, 'sources.marisa')

    def __repr__(self):
        return f'<{type(self).__name__}: {self.path}>'

    def load_manifest(self) -> Manifest:
        return json.load(open(self.manifest_path))
    
    def save_manifest(self, manifest: Manifest):
        json.dump(manifest, open(self.manifest_path, 'w'), indent=4)

