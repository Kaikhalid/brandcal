// D1 access: consistent reads (one batch is one transaction) and optimistic writes. Every write
// batch starts by moving meta.gen from the generation it read to the next one; the guard trigger
// (schema.sql) aborts the whole batch if another write moved it first. Callers then reload and
// try again, so a write is always computed from the state it is applied to.

import { BrandcalError } from "./core";

export type Row = Record<string, unknown>;
export type Cfg = Record<string, unknown>;

export class Conflict extends Error {}

/** db.translate: a trigger's "CODE: message" becomes that error; other failures are BAD_ARGS. */
export function translate(err: unknown): Error {
  const text = err instanceof Error ? err.message : String(err);
  if (text.includes("CONFLICT: the calendar changed")) return new Conflict(text);
  const m = /([A-Z][A-Z_]+): (.*?)(?::\s*SQLITE_[A-Z_]+)?$/s.exec(text.replace(/^D1_ERROR:\s*/, ""));
  if (m && m[1] && m[1] !== "D1_ERROR" && !m[1].startsWith("SQLITE")) {
    return new BrandcalError(m[1], m[2] ?? "");
  }
  const plain = text.replace(/^D1_ERROR:\s*/, "").replace(/:\s*SQLITE_[A-Z_]+$/, "");
  return new BrandcalError("BAD_ARGS", plain);
}

export class Batch {
  stmts: D1PreparedStatement[] = [];
  constructor(private db: D1Database, private gen: number) {}
  add(sql: string, ...params: unknown[]): void {
    this.stmts.push(this.db.prepare(sql).bind(...params.map((p) => (p === undefined ? null : p))));
  }
  async commit(): Promise<number> {
    const guard = this.db.prepare("UPDATE meta SET v = ? WHERE k = 'gen'").bind(String(this.gen + 1));
    try {
      await this.db.batch([guard, ...this.stmts]);
    } catch (err) {
      throw translate(err);
    }
    return this.gen + 1;
  }
}

/** Run ``fn`` until its batch commits without a conflict (3 tries). */
export async function retrying<T>(fn: () => Promise<T>): Promise<T> {
  for (let i = 0; i < 3; i++) {
    try {
      return await fn();
    } catch (err) {
      if (!(err instanceof Conflict)) throw err;
    }
  }
  throw new BrandcalError(
    "INTERNAL", "The calendar was busy and the change was not saved.", "Try again in a moment.",
  );
}

export async function readAll(db: D1Database, stmts: D1PreparedStatement[]): Promise<Row[][]> {
  const res = await db.batch(stmts);
  return res.map((r) => (r.results ?? []) as Row[]);
}

export function parseCfg(rows: Row[]): { gen: number; cfg: Cfg } {
  let gen = 0;
  let cfg: Cfg = {};
  for (const r of rows) {
    if (r.k === "gen") gen = Number(r.v);
    if (r.k === "config") cfg = JSON.parse(String(r.v)) as Cfg;
  }
  return { gen, cfg };
}

export const META_SQL = "SELECT k, v FROM meta WHERE k IN ('gen', 'config')";
