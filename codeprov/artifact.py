import os
import json
import logging
import tempfile
import tarfile
import shutil
import requests

from typing import Callable, BinaryIO
from dataclasses import dataclass, asdict

from tqdm.auto import tqdm


CODEPROV_HOME = os.path.expanduser(
    os.getenv(
        'CODEPROV_HOME',
        os.path.join(os.getenv('XDG_CACHE_HOME', '~/.cache'), 'codeprov'),
    )
)
CODEPROV_OFFLINE = os.getenv('CODEPROV_OFFLINE', '0') in ('1', 'yes')
URL = 'https://github.com/Trussed-ai/codeprov-datasets/releases/download/{name}/{name}.tar.lzma'

logger = logging.getLogger(__name__)


class OfflineModeIsEnabled(Exception):
    pass


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
        self.name = os.path.basename(name)

        if name != self.name:
            self.path = os.path.abspath(os.path.expanduser(name))
        else:
            self.path = os.path.abspath(os.path.join(CODEPROV_HOME, name))

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

    def files_exists(self):
        return (
            os.path.exists(self.manifest_path)
            and os.path.exists(self.digests_bloom_path)
            and os.path.exists(self.digests_trie_path)
            and os.path.exists(self.sources_trie_path)
        )

    def download_artifact(
        self,
        url: str | None = None,
        after: Callable[[BinaryIO], None] | None = None,
    ):
        name = os.path.basename(self.name)
        url = (url or URL)

        if '{name}' in url:
            url = url.format(name=name)
        else:
            url = f'{url.rstrip("/")}/{name}'

        if CODEPROV_OFFLINE:
            raise OfflineModeIsEnabled(
                f'Cannot reach {url}: offline mode is enabled. To disable it, please unset the `CODEPROV_OFFLINE` environment variable.'
            )

        with tempfile.NamedTemporaryFile() as f:
            with tqdm(unit='B', unit_scale=True, desc=name, disable=None) as bar:
                for response in maybe_multifile(url):
                    for chunk in response.iter_content(32768):
                        bar.update(len(chunk))
                        f.write(chunk)

            f.seek(0)
            (after or self.extract_artifact)(f)

    def extract_artifact(self, fileobj: BinaryIO):
        logger.info('Extract to %s', self.path)
        os.makedirs(self.path, exist_ok=True)

        tar = tarfile.open(mode='r:xz', fileobj=fileobj)
        tar.extractall(self.path, filter='data')

    def save_artifact(self, fileobj: BinaryIO, dst=''):
        filename = f'{self.name}.tar.lzma'

        if dst:
            path = os.path.join(os.path.abspath(os.path.expanduser(dst)), filename)
        else:
            path = os.path.join(CODEPROV_HOME, filename)

        logger.info('Save to %s', path)
        shutil.move(fileobj.name, path)


def maybe_multifile(url):
    response1 = requests.get(url, stream=True)
    urls = (f'{url}.{i:02}' for i in range(100))

    if response1.status_code == 404:
        next_url = next(urls)
        response2 = requests.get(next_url, stream=True)

        if response2.status_code == 200:
            logger.info('Multifile artifact found')
            logger.info('Download %s', next_url)
            yield response2

            for next_url in urls:
                response = requests.get(next_url, stream=True)

                if response.status_code == 404:
                    return

                response.raise_for_status()
                logger.info('Download %s', next_url)
                yield response
        else:
            response1.raise_for_status()
    else:
        response1.raise_for_status()
        logger.info('Download %s', url)
        yield response1


if __name__ == '__main__':
    logging.basicConfig(format='%(asctime)s: %(message)s', level=logging.INFO)

    import sys
    import argparse

    argparser = argparse.ArgumentParser()
    commands = argparser.add_subparsers(dest='command')

    cmd = commands.add_parser('download', help='Download an artifact archive')
    cmd.add_argument('name')
    cmd.add_argument('path', nargs='?', default='.')

    cmd = commands.add_parser(
        'install', help='Download and extract an artifact archive'
    )
    cmd.add_argument('name')
    cmd.add_argument('path', nargs='?', default=CODEPROV_HOME)

    args = argparser.parse_args(args=(sys.argv[1:] or ['--help']))
    meta = Metadata(args.name)

    if args.command == 'download':
        meta.download_artifact(after=lambda f: meta.save_artifact(f, args.path))

    if args.command == 'install':
        meta.download_artifact()
