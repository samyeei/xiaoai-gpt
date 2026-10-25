import { spawn } from "node:child_process";

// Each detached POSIX child leads a group containing its descendants. Only
// child-owned group IDs are signalled; the manager's group is never targeted.
export function signalOwned(child, signal) {
  try {
    if (Number.isInteger(child.pid) && child.pid > 1)
      process.kill(-child.pid, signal);
    else child.kill(signal); // Test doubles / failed spawn without a PID.
  } catch (error) {
    if (error.code !== "ESRCH") throw error;
  }
}

export class ChildGroup {
  constructor(
    specs,
    { spawnFn = spawn, delay = 500, killAfter = 5000, maxRestarts = 5 } = {},
  ) {
    Object.assign(this, { specs, spawnFn, delay, killAfter, maxRestarts });
    this.children = new Map();
    this.timers = new Set();
    this.stopping = false;
  }

  freeze() {
    this.stopping = true;
    for (const timer of this.timers) clearTimeout(timer);
    this.timers.clear();
  }

  start(name) {
    if (this.stopping) return;
    const spec = this.specs[name];
    if (!spec) throw Error("Unknown child");
    const entry = this.children.get(name) ?? { attempts: 0 };
    if (entry.process) return;
    entry.state = "starting";
    this.children.set(name, entry);
    const child = this.spawnFn(spec.command, spec.args, {
      cwd: spec.cwd,
      env: { ...process.env, ...spec.env },
      detached: true,
      stdio: ["ignore", "ignore", "ignore"],
    });
    entry.process = child;
    child.once("spawn", () => {
      entry.state = "running";
    });
    let ended = false;
    const end = () => {
      if (ended) return;
      ended = true;
      // Also remove descendants when a service crashes or exits before its
      // own cleanup completes. Do this before allowing a replacement spawn.
      signalOwned(child, "SIGKILL");
      entry.process = null;
      entry.state = this.stopping ? "stopped" : "exited";
      if (!this.stopping && entry.attempts++ < this.maxRestarts) {
        entry.state = "backoff";
        const timer = setTimeout(
          () => {
            this.timers.delete(timer);
            this.start(name);
          },
          Math.min(30000, this.delay * 2 ** (entry.attempts - 1)),
        );
        this.timers.add(timer);
      }
    };
    child.once("exit", end);
    child.once("error", end);
  }

  status() {
    return Object.fromEntries(
      [...this.children].map(([name, entry]) => [
        name,
        { state: entry.state, restarts: entry.attempts },
      ]),
    );
  }

  async shutdownWith(stopOther = async () => {}) {
    this.freeze();
    await Promise.all([this.stop(), stopOther()]);
  }

  async stop() {
    this.freeze();
    await Promise.all(
      [...this.children.values()].map(
        (entry) =>
          new Promise((resolve) => {
            const child = entry.process;
            if (!child) {
              entry.state = "stopped";
              resolve();
              return;
            }
            const timer = setTimeout(
              () => signalOwned(child, "SIGKILL"),
              this.killAfter,
            );
            child.once("exit", () => {
              clearTimeout(timer);
              resolve();
            });
            signalOwned(child, "SIGTERM");
          }),
      ),
    );
  }
}
