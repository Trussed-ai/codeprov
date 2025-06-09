import warnings

from dataclasses import dataclass
from collections.abc import Buffer

from rbloom import Bloom
from marisa_trie import Trie, BinaryTrie

from codeprov.artifact import Metadata, OfflineModeIsEnabled
from codeprov.parser import LanguageParser, Block


@dataclass(slots=True)
class Source:
    id: int
    repo: str
    revision: str
    path: str
    stars: int
    licenses: list[str]

    def github_permalink(self):
        return f'https://github.com/{self.repo}/blob/{self.revision}/{self.path.lstrip("/")}'


@dataclass(slots=True)
class Snippet:
    block: Block
    source: Source


class SourcesTrie:
    def __init__(self, *args, **kwargs):
        self.trie = Trie(*args, **kwargs)

    def load(self, path: str, mmap=True):
        self.trie = (self.trie.mmap if mmap else self.trie.load)(path)
        return self

    def get_source(self, repo: str, revision: str, path: str):
        key = repo + '\1' + revision + '\1' + path + '\1'
        source, source_id = next(self.trie.iteritems(key), (None, None))

        if source is not None:
            repo, revision, path, stars, *licenses = source.split('\1')
            return Source(source_id, repo, revision, path, int(stars), licenses)

    def get_source_by_id(self, source_id: int):
        try:
            source = self.trie.restore_key(source_id)
        except KeyError:
            return None

        repo, revision, path, stars, *licenses = source.split('\1')
        return Source(source_id, repo, revision, path, int(stars), licenses)


class DigestsTrie:
    def __init__(self, *args, **kwargs):
        self.trie = BinaryTrie(*args, **kwargs)

    def load(self, path: str, mmap=True):
        self.trie = (self.trie.mmap if mmap else self.trie.load)(path)
        return self

    def get(self, digest: bytes):
        key = next(self.trie.iterkeys(digest), None)

        if key is not None:
            return int.from_bytes(key[-4:])


class Scanner:
    def __init__(
        self,
        parser: LanguageParser,
        sources: SourcesTrie,
        digests: DigestsTrie,
        digests_bloom: Bloom,
        metadata: Metadata | None = None,
    ):
        self.parser = parser
        self.sources = sources
        self.digests = digests
        self.digests_bloom = digests_bloom
        self.metadata = metadata

    def __repr__(self):
        return f'<{type(self).__name__} parser={self.parser}>'

    @classmethod
    def from_dataset_name(
        cls,
        name: str,
        parser_timeout_micros=1000000,
        sources_mmap=True,
        digests_mmap=True,
        offline=False,
        url: str | None = None,
    ):
        metadata = Metadata(name)

        if not metadata.files_exists():
            if offline:
                raise OfflineModeIsEnabled(
                    f'Cannot download {name} dataset: offline mode is enabled.'
                )

            metadata.download_artifact(url=url, after=metadata.extract_artifact)

        manifest = metadata.load_manifest()
        sources = SourcesTrie().load(metadata.sources_trie_path, sources_mmap)
        digests = DigestsTrie().load(metadata.digests_trie_path, digests_mmap)
        digests_bloom = Bloom.load(metadata.digests_bloom_path, bloom_hash)

        parser = LanguageParser.get_class(manifest.language, manifest.parser)(
            parser_timeout_micros
        )
        parser.search_nodes = None # All

        return cls(
            parser=parser,
            sources=sources,
            digests=digests,
            digests_bloom=digests_bloom,
            metadata=metadata,
        )

    def scan(self, source: str | Buffer):
        for digest, block in self.parser.parse(source).digests().items():
            if digest not in self.digests_bloom:
                continue

            if (src_id := self.digests.get(digest[:8])) is None:
                continue

            if (source := self.sources.get_source_by_id(src_id)) is None:
                warnings.warn(
                    f'Digest {block.digest.hexdigest()} found, but corresponding attribution entry missing.'
                )
                continue

            yield Snippet(block=block, source=source)


def bloom_hash(digest: bytes):
    return int.from_bytes(digest[:16], 'big', signed=True)
