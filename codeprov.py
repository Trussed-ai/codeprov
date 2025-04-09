from hashlib import blake2s
from dataclasses import dataclass
from collections.abc import Buffer
from typing import Callable, Iterable, ClassVar, Self


from tree_sitter import Language, Parser, Tree, Node
from marisa_trie import Trie, BinaryTrie
from rbloom import Bloom


def bloom_hash(digest: bytes):
    return int.from_bytes(digest[:16], 'big', signed=True)


@dataclass(slots=True, eq=False, init=False)
class Block:
    node: Node
    tokens: list[bytes]
    digest: blake2s

    def __init__(self, node: Node):
        self.node = node
        self.tokens = []
        self.digest = blake2s(digest_size=16)


class LanguageParser:
    classes: ClassVar[dict[str, type[Self]]] = {}
    language: ClassVar[str] = 'Base'
    name: ClassVar[str] = 'block1'

    digest_nodes: ClassVar[frozenset[str]] = frozenset({'block'})
    digest_skip_nodes: ClassVar[frozenset[str]] = frozenset({'comment'})
    digest_min_nodes: ClassVar[int] = 30
    search_nodes: ClassVar[frozenset[str] | None] = None

    tree: Tree | None
    blocks: dict[Block, Block | None]

    def __init__(self, timeout_micros=1000000):
        self.tree = None
        self.blocks = {}
        self.parser = Parser(Language(self.grammar()), timeout_micros=timeout_micros)

    def __init_subclass__(cls):
        if cls.language or cls.name:
            cls.classes[cls.language, cls.name] = cls

    @classmethod
    def get_class(cls, language: str, name: str):
        try:
            return cls.classes[language, name]
        except KeyError:
            raise ValueError(f'Parser "{name}" for {language} not found') from None

    def grammar(self) -> object:
        raise NotImplementedError

    def display(self):
        lines = []

        for block, pblock in self.blocks.items():
            lines.append(f'{block.digest.hexdigest()} ntokens={len(block.tokens)}')
            lines.append(repr(b''.join(block.tokens)))
            lines.append(block.node.text.decode() + '\n')

        return '\n'.join(lines)

    def parse(self, source: str | Buffer):
        self.parser.reset()
        self.tree = None
        self.blocks = {}

        if isinstance(source, str):
            source = source.encode()

        self.tree = self.parser.parse(source)
        self.lookup(self.tree.root_node)

        for i in self.blocks:
            i.digest.update(b''.join(i.tokens))

    def lookup(self, node: Node):
        for i in node.children:
            if i.type in self.digest_nodes:
                block = Block(i)
                self.blocks[block] = None
                self.lookup_compute(block, i)

            elif self.search_nodes is None or i.type in self.search_nodes:
                self.lookup(i)

    def lookup_compute(self, block: Block, node: Node):
        for i in node.children:
            # Skip orphan literals
            if i.type == 'expression_statement' and i.child_count == 1:
                if i.child(0).type == 'string':
                    continue

            if i.type in self.digest_skip_nodes:
                continue

            if self.search_nodes is not None:
                if i.type in self.search_nodes:
                    if i.descendant_count > self.digest_min_nodes:
                        self.lookup(i)
                        continue

            if i.type in self.digest_nodes:
                if i.descendant_count > self.digest_min_nodes:
                    nested_block = Block(i)
                    self.blocks[nested_block] = block
                    self.lookup_compute(nested_block, i)
                    continue

            if i.child_count == 0 and i.text is not None:
                block.tokens.append(i.text)
                continue

            self.lookup_compute(block, i)

        # Top-level call
        if block.node is node:
            if len(block.tokens) < self.digest_min_nodes:
                if (parent := self.blocks.pop(block, None)) is not None:
                    parent.tokens.extend(block.tokens)


class PythonParser(LanguageParser):
    language: ClassVar[str] = 'Python'
    name: ClassVar[str] = 'block1'

    search_nodes: ClassVar[frozenset[str]] = frozenset(
        {
            'decorated_definition',
            'class_definition',
            'function_definition',
        }
    )
    digest_nodes: ClassVar[frozenset[str]] = frozenset(
        {
            'block',
        }
    )
    digest_skip_nodes: ClassVar[frozenset[str]] = frozenset(
        {
            'comment',
            'decorator',
            ';',
        }
    )

    def grammar(self):
        from tree_sitter_python import language

        return language()


class JavaScriptParser(LanguageParser):
    language: ClassVar[str] = 'JavaSript'
    name: ClassVar[str] = 'block1'

    search_nodes: ClassVar[frozenset[str] | None] = None
    digest_nodes: ClassVar[frozenset[str]] = frozenset(
        {
            'statement_block',
        }
    )
    digest_skip_nodes: ClassVar[frozenset[str]] = frozenset(
        {
            'comment',
            '{',
            '}',
            ';',
        }
    )

    def grammar(self):
        from tree_sitter_javascript import language

        return language()


class JavaParser(LanguageParser):
    language: ClassVar[str] = 'Java'
    name: ClassVar[str] = 'block1'

    search_nodes: ClassVar[frozenset[str]] = frozenset(
        {
            'class_declaration',
            'class_body',
            'method_declaration',
        }
    )
    digest_nodes: ClassVar[frozenset[str]] = frozenset(
        {
            'block',
            'lambda_expression',
        }
    )
    digest_skip_nodes: ClassVar[frozenset[str]] = frozenset(
        {
            'line_comment',
            'block_comment',
            '{',
            '}',
            ';',
        }
    )

    def grammar(self):
        from tree_sitter_java import language

        return language()


@dataclass(slots=True)
class Source:
    id: int
    repo: str
    revision: str
    path: str
    stars: int
    licenses: list[str]


class SourcesTrie:
    def __init__(self, *args, **kwargs):
        self.trie = Trie(*args, **kwargs)

    def load(self, path: str):
        self.trie = self.trie.load(path)
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


