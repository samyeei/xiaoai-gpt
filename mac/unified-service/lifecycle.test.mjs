import test from "node:test";
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { ChildGroup } from "./lifecycle.mjs";
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
test("bounded retries and no retries after shutdown", async () => {
  const spawned = [];
  const g = new ChildGroup(
    { one: { command: "fixed", args: [] } },
    {
      delay: 2,
      maxRestarts: 2,
      spawnFn: () => {
        const c = new EventEmitter();
        c.kill = () => queueMicrotask(() => c.emit("exit"));
        spawned.push(c);
        return c;
      },
    },
  );
  g.start("one");
  spawned[0].emit("exit");
  await wait(10);
  spawned[1].emit("exit");
  await wait(10);
  spawned[2].emit("exit");
  await wait(10);
  assert.equal(spawned.length, 3);
  await g.stop();
  g.start("one");
  assert.equal(spawned.length, 3);
});
test("shutdown escalates stuck children and cancels pending restart", async () => {
  let kills = [];
  const g = new ChildGroup(
    { one: { command: "fixed", args: [] } },
    {
      killAfter: 5,
      spawnFn: () => {
        const c = new EventEmitter();
        c.kill = (s) => {
          kills.push(s);
          if (s === "SIGKILL") queueMicrotask(() => c.emit("exit"));
        };
        return c;
      },
    },
  );
  g.start("one");
  await g.stop();
  assert.deepEqual(kills, ["SIGTERM", "SIGKILL", "SIGKILL"]);
  assert.equal(g.status().one.state, "stopped");
});
test("shutdown freezes restarts while pairing is still stopping", async () => {
  const children = [];
  const g = new ChildGroup(
    { one: { command: "fixed", args: [] } },
    {
      delay: 2,
      spawnFn: () => {
        const c = new EventEmitter();
        c.kill = () => queueMicrotask(() => c.emit("exit"));
        children.push(c);
        return c;
      },
    },
  );
  g.start("one");
  children[0].emit("exit");
  let finishPair;
  const pairStop = new Promise((r) => (finishPair = r));
  const stopping = g.shutdownWith(() => pairStop);
  await wait(15);
  assert.equal(children.length, 1);
  finishPair();
  await stopping;
});
test("real process group cleans grandchild after forced stop and parent crash", async (t) => {
  const { mkdtempSync, readFileSync, existsSync, rmSync } = await import(
    "node:fs"
  );
  const { tmpdir } = await import("node:os");
  const { join } = await import("node:path");
  const dir = mkdtempSync(join(tmpdir(), "xiaoai-group-"));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  for (const crash of [false, true]) {
    const file = join(dir, String(crash));
    const code = `const {spawn}=require('node:child_process');const fs=require('node:fs');const c=spawn(process.execPath,['-e',"process.on('SIGTERM',()=>{});setInterval(()=>{},1000)"],{stdio:'ignore'});fs.writeFileSync(${JSON.stringify(file)},String(c.pid));process.on('SIGTERM',()=>{});${crash ? "setTimeout(()=>process.exit(3),100)" : "setInterval(()=>{},1000)"}`;
    const g = new ChildGroup(
      { fixture: { command: process.execPath, args: ["-e", code] } },
      { killAfter: 20, maxRestarts: 0 },
    );
    g.start("fixture");
    for (let n = 0; n < 100 && !existsSync(file); n++) await wait(10);
    assert.ok(existsSync(file));
    const pid = Number(readFileSync(file));
    if (crash) await wait(150);
    else await g.stop();
    let alive = true;
    for (let n = 0; n < 100; n++) {
      try {
        process.kill(pid, 0);
      } catch {
        alive = false;
        break;
      }
      await wait(10);
    }
    assert.equal(alive, false, "grandchild must be reaped");
    await g.stop();
  }
});
