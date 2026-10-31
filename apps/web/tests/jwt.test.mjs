import test from "node:test";
import assert from "node:assert/strict";
import { decodeClaims, isExpired, roleFromToken } from "../lib/jwt.ts";

const b64 = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
const tok = (claims) => `${b64({ alg: "HS256" })}.${b64(claims)}.sig`;
const future = Math.floor(Date.now() / 1000) + 3600;

test("a token with exactly one known role maps to that role", () => {
  assert.equal(roleFromToken(tok({ roles: ["reviewer"] })), "reviewer");
  assert.equal(roleFromToken(tok({ roles: ["provider"] })), "provider");
});

test("zero, several or unknown roles are rejected", () => {
  assert.equal(roleFromToken(tok({ roles: [] })), null);
  assert.equal(roleFromToken(tok({ roles: ["reviewer", "patient"] })), null);
  assert.equal(roleFromToken(tok({ roles: ["admin"] })), null);
  assert.equal(roleFromToken("not-a-jwt"), null);
});

test("expiry is checked with a small skew", () => {
  assert.equal(isExpired(tok({ exp: future })), false);
  assert.equal(isExpired(tok({ exp: future - 7200 })), true);
  assert.equal(isExpired(tok({})), true);
  assert.equal(isExpired("garbage"), true);
});

test("garbage decodes to null instead of throwing", () => {
  assert.equal(decodeClaims("a.b.c"), null);
});
