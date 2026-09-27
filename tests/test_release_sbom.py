"""Declared build and platform packages must survive release SBOM generation."""

import copy

import pytest

from scripts.ci.release_sbom import bind_inventory

SHA = "a" * 40
INVENTORY = {"source_sha": SHA, "ecosystems": [
    {"ecosystem": "python", "packages": [{"name": "build_tool", "version": "1", "licenses": ["MIT"]}]},
    {"ecosystem": "cargo", "packages": [{"name": "native", "version": "2"}]},
    {"ecosystem": "npm", "packages": [{"name": "@scope/platform", "version": "3"}]},
]}
BOM = {"bomFormat": "CycloneDX", "specVersion": "1.6", "components": [
    {"name": "build-tool", "version": "1", "purl": "pkg:pypi/build-tool@1", "bom-ref": "python"},
    {"name": "native", "version": "2", "purl": "pkg:cargo/native@2", "bom-ref": "cargo"},
    {"group": "@scope", "name": "platform", "version": "3", "purl": "pkg:npm/%40scope/platform@3", "bom-ref": "npm"},
], "dependencies": [{"ref": "python", "dependsOn": ["cargo"]}]}


def test_bind_inventory_preserves_graph_and_publisher_evidence():
    bom = bind_inventory(copy.deepcopy(BOM), INVENTORY, SHA)
    assert bom["dependencies"] == BOM["dependencies"]
    assert bom["components"][0]["licenses"] == [{"license": {"name": "MIT"}}]
    assert bom["metadata"]["properties"][0]["value"] == SHA


@pytest.mark.parametrize("index", range(3))
def test_missing_build_or_native_platform_package_fails_closed(index):
    bom = copy.deepcopy(BOM)
    del bom["components"][index]
    with pytest.raises(ValueError, match="SBOM omits"):
        bind_inventory(bom, INVENTORY, SHA)


@pytest.mark.parametrize("inventory", [{"source_sha": "b" * 40}, {"source_sha": SHA, "ecosystems": []}])
def test_wrong_source_or_empty_inventory_is_not_release_evidence(inventory):
    with pytest.raises(ValueError):
        bind_inventory(copy.deepcopy(BOM), inventory, SHA)


def test_forged_component_url_cannot_hide_wrong_artifact_version():
    bom = copy.deepcopy(BOM)
    bom["components"][0]["version"] = "2"
    with pytest.raises(ValueError, match="metadata disagrees"):
        bind_inventory(bom, INVENTORY, SHA)


@pytest.mark.parametrize("wrong_parent", [False, True])
def test_bundled_distribution_projects_its_own_component_and_parent_edge(wrong_parent):
    inventory = copy.deepcopy(INVENTORY)
    owner = inventory["ecosystems"][0]["packages"][0]
    owner["artifact_sha256"] = "b" * 64
    child = {"name": "vendored", "version": "2", "licenses": ["MIT"],
             "artifact_sha256": ("d" if wrong_parent else "b") * 64,
             "metadata_sha256": "c" * 64, "metadata_path": "module/vendor/vendored-2.dist-info/METADATA",
             "bundled_in": {"name": owner["name"], "version": owner["version"]}}
    inventory["ecosystems"][0]["packages"].append(child)
    if wrong_parent:
        with pytest.raises(ValueError, match="parent artifact"):
            bind_inventory(copy.deepcopy(BOM), inventory, SHA)
        return
    bom = bind_inventory(copy.deepcopy(BOM), inventory, SHA)
    component = next(c for c in bom["components"] if c["name"] == "vendored")
    assert component["purl"] == "pkg:pypi/vendored@2"
    assert bom["dependencies"][0]["dependsOn"] == ["cargo", component["bom-ref"]]
    assert component["licenses"] == [{"license": {"name": "MIT"}}]
