"""Command line: ``claimlens {generate,train,eval,demo,token,register-policy,upload-model,init-search,worker}``."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from claimlens.security import configure_logging
from claimlens.settings import get_settings


def _cmd_generate(a: argparse.Namespace) -> int:
    from claimlens.synthetic.generator import generate_dataset

    out = Path(a.out)
    for c in generate_dataset(a.n, seed=a.seed, tenant_id=a.tenant):
        d = out / c.case_id
        d.mkdir(parents=True, exist_ok=True)
        for name, text in c.documents.items():
            (d / name).write_text(text, encoding="utf-8")
        (d / "policy.json").write_text(c.policy.model_dump_json(indent=2))
        (d / "truth.json").write_text(
            json.dumps(
                {
                    "label": c.label,
                    "probability": round(c.probability, 4),
                    "causes": c.causes,
                    "bill": json.loads(c.truth_bill.model_dump_json()),
                },
                indent=2,
            )
        )
    print(f"wrote {a.n} cases to {out}")
    return 0


def _cmd_train(a: argparse.Namespace) -> int:
    from claimlens.ml.train_risk import train

    m = train(n=a.n, seed=a.seed, model_dir=get_settings().model_dir)
    print(
        json.dumps(
            {
                "version": m["version"],
                "overall": m["metrics"]["overall"],
                "gate_passed": m["gate"]["passed"],
            },
            indent=2,
        )
    )
    for c in m["gate"]["checks"]:
        print(("PASS " if c["passed"] else "FAIL ") + c["check"] + ": " + c["detail"])
    return 0 if m["gate"]["passed"] else 2


def _cmd_eval(a: argparse.Namespace) -> int:
    from claimlens.evaluation import run_eval

    run_eval(n=a.n, seed=a.seed, model_dir=get_settings().model_dir, out_dir=Path(a.out))
    print((Path(a.out) / "eval_report.md").read_text())
    return 0


def _cmd_token(a: argparse.Namespace) -> int:
    import jwt

    s = get_settings()
    if s.auth_mode != "dev":
        print("tokens can only be minted in dev auth mode", file=sys.stderr)
        return 1
    now = datetime.now(UTC)
    claims = {
        "sub": a.subject,
        "tenant_id": a.tenant,
        "roles": [a.role],
        "aud": "claimlens-dev",
        "iat": now,
        "exp": now + timedelta(hours=a.hours),
    }
    print(jwt.encode(claims, s.dev_jwt_secret, algorithm="HS256"))
    return 0


def _cmd_demo(a: argparse.Namespace) -> int:
    from datetime import date

    from claimlens.container import build_container
    from claimlens.domain.models import Role
    from claimlens.process import register_policy, run_worker_once
    from claimlens.services import ClaimService, Principal
    from claimlens.synthetic.generator import generate_dataset

    s = get_settings()
    c = build_container(s)
    svc = ClaimService(c)
    provider, reviewer = (
        Principal("provider-demo", "demo", Role.PROVIDER),
        Principal("reviewer-demo", "demo", Role.REVIEWER),
    )
    cases = generate_dataset(a.n, seed=a.seed, tenant_id="demo", as_of=date.today())
    for case in cases:
        register_policy(c, case.policy)
        claim = svc.create_claim(provider, case.policy.policy_id, True)
        for name, text in case.documents.items():
            svc.add_document(provider, claim.claim_id, name, "text/plain", text.encode())
        svc.submit(provider, claim.claim_id)
    while run_worker_once(c, 10):
        pass
    print(
        f"Reviewer queue for tenant 'demo' ({len(cases)} synthetic claims), highest modelled risk first:\n"
    )
    for item in svc.reviewer_queue(reviewer)[:10]:
        p = f"{item.risk_probability:.0%}" if item.risk_probability is not None else "n/a"
        print(
            f"{item.claim_id}  {item.status.value:<10} risk {p:>4}{f' ({item.risk_band})' if item.risk_band else ''}  flags={item.n_flags}  {item.top_reason or ''}"
        )
    print(
        f"\nData directory: {s.data_dir.resolve()}  (start the API with `make api`, then `claimlens token --tenant demo --role reviewer`)"
    )
    return 0


def _cmd_upload_model(a: argparse.Namespace) -> int:
    from claimlens.adapters.azure.blob import AzureBlobStore

    s = get_settings()
    root = s.model_dir / "risk"
    pointer = root / "CURRENT"
    if not pointer.exists():
        print("no promoted model found (the release gate must pass first)", file=sys.stderr)
        return 1
    version = pointer.read_text().strip()
    store = AzureBlobStore(a.storage_url, s.model_container)
    for f in sorted((root / version).iterdir()):
        store.put(f"risk/{version}/{f.name}", f.read_bytes(), "application/octet-stream")
    print(f"risk/{version}")  # last line = value for CLAIMLENS_MODEL_BLOB_PREFIX
    return 0


def _cmd_init_search(a: argparse.Namespace) -> int:
    from claimlens.adapters.azure.search import ensure_index

    s = get_settings()
    ensure_index(s.search_endpoint, s.search_index)
    print(f"index '{s.search_index}' is ready")
    return 0


def _cmd_register_policy(a: argparse.Namespace) -> int:
    from datetime import date

    from claimlens.container import build_container
    from claimlens.process import register_policy
    from claimlens.rules.policy_loader import instantiate_policy

    policy = instantiate_policy(
        a.product,
        policy_id=a.policy_id,
        tenant_id=a.tenant,
        holder_name=a.holder,
        start_date=date.fromisoformat(a.start_date),
        network_providers=a.network_provider,
    )
    register_policy(build_container(get_settings()), policy)
    print(f"registered policy '{policy.policy_id}' ({policy.product_name}) for tenant '{a.tenant}'")
    return 0


def _cmd_worker(a: argparse.Namespace) -> int:
    from claimlens.container import build_container
    from claimlens.process import run_worker_once

    configure_logging()
    c = build_container(get_settings())
    while True:
        if run_worker_once(c, 5) == 0:
            time.sleep(a.poll)
        if a.once:
            return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="claimlens")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="write synthetic cases to disk")
    g.add_argument("--n", type=int, default=20)
    g.add_argument("--seed", type=int, default=7)
    g.add_argument("--tenant", default="demo")
    g.add_argument("--out", default="data/synthetic")
    g.set_defaults(fn=_cmd_generate)
    t = sub.add_parser("train", help="train, calibrate, gate and package the risk model")
    t.add_argument("--n", type=int, default=5000)
    t.add_argument("--seed", type=int, default=42)
    t.set_defaults(fn=_cmd_train)
    e = sub.add_parser("eval", help="run the evaluation harness on fresh synthetic data")
    e.add_argument("--n", type=int, default=600)
    e.add_argument("--seed", type=int, default=1234)
    e.add_argument("--out", default="reports")
    e.set_defaults(fn=_cmd_eval)
    k = sub.add_parser("token", help="mint a dev JWT (dev auth mode only)")
    k.add_argument("--subject", default="user-1")
    k.add_argument("--tenant", default="demo")
    k.add_argument("--role", choices=["patient", "provider", "reviewer"], default="reviewer")
    k.add_argument("--hours", type=int, default=8)
    k.set_defaults(fn=_cmd_token)
    d = sub.add_parser(
        "demo", help="load synthetic claims, process them and show the reviewer queue"
    )
    d.add_argument("--n", type=int, default=25)
    d.add_argument("--seed", type=int, default=11)
    d.set_defaults(fn=_cmd_demo)
    u = sub.add_parser(
        "upload-model", help="publish the promoted model bundle to the models container"
    )
    u.add_argument("--storage-url", required=True)
    u.set_defaults(fn=_cmd_upload_model)
    i = sub.add_parser(
        "init-search", help="create or update the Azure AI Search index (run once per environment)"
    )
    i.set_defaults(fn=_cmd_init_search)
    r = sub.add_parser(
        "register-policy", help="create a policy from a product template and index its clauses"
    )
    r.add_argument("--tenant", required=True)
    r.add_argument("--policy-id", required=True)
    r.add_argument("--product", required=True, help="ppo_gold | hmo_silver | hdhp_bronze")
    r.add_argument("--holder", required=True)
    r.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    r.add_argument("--network-provider", action="append", default=[])
    r.set_defaults(fn=_cmd_register_policy)
    w = sub.add_parser("worker", help="run the queue worker")
    w.add_argument("--poll", type=float, default=2.0)
    w.add_argument("--once", action="store_true")
    w.set_defaults(fn=_cmd_worker)
    args = ap.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
