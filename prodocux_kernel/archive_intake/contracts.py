"""Schema and reason lookup for the frozen archive wire contracts."""

import json
from functools import lru_cache
from pathlib import Path

import rfc8785
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from .decoders import ArchiveError

DATA = Path(__file__).resolve().parents[1] / "schemas"


def load(name):
    return json.loads((DATA / name).read_bytes())


@lru_cache(maxsize=1)
def schemas():
    documents = {
        path.name.removesuffix(".schema.json"): json.loads(path.read_bytes())
        for path in DATA.glob("prodocux_archive_*.schema.json")
    }
    registry = Registry().with_resources(
        (value["$id"], Resource.from_contents(value)) for value in documents.values()
    )
    return {
        key: Draft202012Validator(value, registry=registry)
        for key, value in documents.items()
    }


def validate(name, value):
    if not schemas()["prodocux_archive_" + name].is_valid(value):
        raise ArchiveError("MALFORMED_REQUEST")


def digest(value):
    from hashlib import sha256

    return sha256(rfc8785.dumps(value)).hexdigest()


def strict_load(raw):
    def unique(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ArchiveError("MALFORMED_REQUEST")
            value[key] = item
        return value

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
        rfc8785.dumps(value)
    except (ValueError, TypeError, RecursionError) as error:
        raise ArchiveError("MALFORMED_REQUEST") from error
    return value


@lru_cache(maxsize=1)
def reasons():
    return {
        row["code"]: row for row in load("archive_reason_catalog.json")["reason_codes"]
    }
