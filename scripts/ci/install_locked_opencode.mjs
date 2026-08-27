#!/usr/bin/env node

import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { spawnSync } from "node:child_process"
import { createRequire } from "node:module"

const require = createRequire(import.meta.url)
const cliPackagePath = require.resolve("opencode-ai/package.json")
const cliPackage = JSON.parse(fs.readFileSync(cliPackagePath, "utf8"))
const platform = { darwin: "darwin", linux: "linux", win32: "windows" }[os.platform()]
const arch = { x64: "x64", arm64: "arm64", arm: "arm" }[os.arch()]

if (!platform || !arch) throw new Error("unsupported OpenCode runner platform")

const prefix = `opencode-${platform}-${arch}`
const candidates = Object.entries(cliPackage.optionalDependencies ?? {})
  .filter(([name]) => name === prefix || name.startsWith(`${prefix}-`))
  .sort(([left], [right]) => left.localeCompare(right))
let installedCandidate = false

for (const [name, expectedVersion] of candidates) {
  try {
    const packagePath = require.resolve(`${name}/package.json`)
    installedCandidate = true
    const installed = JSON.parse(fs.readFileSync(packagePath, "utf8"))
    if (installed.version !== expectedVersion) {
      throw new Error(`${name} version does not match opencode-ai's locked dependency`)
    }
    const source = path.join(path.dirname(packagePath), "bin", platform === "windows" ? "opencode.exe" : "opencode")
    const target = path.join(path.dirname(cliPackagePath), "bin", "opencode.exe")
    if (!fs.existsSync(source)) continue
    fs.mkdirSync(path.dirname(target), { recursive: true })
    fs.copyFileSync(source, target)
    fs.chmodSync(target, 0o755)
    const verified = spawnSync(target, ["--version"], { stdio: "ignore", windowsHide: true })
    if (verified.status === 0) process.exit(0)
  } catch (error) {
    if (error?.code !== "MODULE_NOT_FOUND") throw error
  }
}

throw new Error(installedCandidate
  ? "no lockfile-authorized OpenCode binary passed its version check"
  : "npm ci did not install a lockfile-authorized OpenCode binary package")
