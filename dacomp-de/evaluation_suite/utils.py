#!/usr/bin/env python3
"""
Utility functions and evaluators for DA-Comp DE evaluation.

Supports two evaluation modes:
- cfs: core-perfect short-circuit to 100; otherwise use progressive flow for per-layer scoring
- cs: per-table hybrid (gold-wrapped) evaluation per layer (single hybrid DB)

JSON is concise and consistent with prior outputs; task_type is DE; evaluation_mode reflects selected mode.
"""
import sys
import json
import yaml
import logging
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple, Any
from datetime import datetime
import duckdb
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ----------------------
# Threshold utilities
# ----------------------

# Schema and scoring helpers

def map_schema(layer: str) -> str:
    return 'mart' if layer == 'marts' else layer


def weighted_score(scores: List[Tuple[float, float]]) -> float:
    total_w = sum(w for _, w in scores)
    if total_w > 0:
        return (sum(s * w for s, w in scores) / total_w) * 100.0
    else:
        return (sum(s for s, _ in scores) / len(scores) * 100.0) if scores else 0.0

def build_summary(layer_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    layer_scores = {lr['layer_name']: lr.get('layer_score', 0) for lr in layer_results}
    return {
        'total_layers': len(layer_results),
        'perfect_layers': sum(1 for s in layer_scores.values() if s >= 1.0),
        'partially_correct_layers': sum(1 for s in layer_scores.values() if 0 < s < 1.0),
        'failed_layers': sum(1 for s in layer_scores.values() if s == 0.0),
        'layer_scores': layer_scores,
    }

def execute_run_py(pred_dir: Path, database_file: str, force_rebuild: bool = False) -> bool:
    """Run pred_dir/run.py and check database_file exists after.

    force_rebuild: when True, delete existing DB file before running.
    """
    run_py = pred_dir / "run.py"
    db_path = pred_dir / database_file
    if not run_py.exists():
        return False
    try:
        if force_rebuild and db_path.exists():
            try:
                db_path.unlink()
            except Exception:
                pass
        subprocess.run([sys.executable, "run.py"], cwd=str(pred_dir), capture_output=True, text=True, timeout=200)
        return db_path.exists()
    except Exception:
        return False


def validate_schemas(db_path: Path, expected_schemas: List[str]) -> bool:
    """Validate business schemas exist; allow mart <-> marts."""
    if not db_path.exists():
        return False
    try:
        conn = duckdb.connect(str(db_path), read_only=True)
        existing = {row[0] for row in conn.execute("SELECT schema_name FROM information_schema.schemata").fetchall()}
        conn.close()
        for schema in expected_schemas:
            if schema in ['information_schema', 'main', 'raw']:
                continue
            ok = (schema in existing) or (schema == 'marts' and 'mart' in existing) or (schema == 'mart' and 'marts' in existing)
            if not ok:
                return False
        return True
    except Exception:
        return False

# ----------------------
# Core accuracy evaluator
# ----------------------

class CoreAccuracyEvaluator:
    """Compare tables across gold and prediction DuckDB databases."""

    def __init__(self, pred_db_path: Path, gold_db_path: Path, config: Dict[str, Any] = None):
        self.pred_db = pred_db_path
        self.gold_db = gold_db_path
        self.config = config or {}

    def compare_table(self, schema: str, table: str) -> bool:
        """Row-hash multiset comparison with diagnostic logging.

        This version performs the intersection-column, per-row-hash grouped comparison
        (Python-aggregated). It logs diagnostic reasons for failure so we can identify
        why a table was judged mismatched (missing columns, count mismatch, timeout,
        or differing row counts by hash).
        """
        try:
            pred_ro = duckdb.connect(str(self.pred_db), read_only=True)
            gold_ro = duckdb.connect(str(self.gold_db), read_only=True)

            def _resolve(conn: duckdb.DuckDBPyConnection, s: str) -> str:
                try:
                    if s in ('mart', 'marts'):
                        names = {r[0] for r in conn.execute("SELECT schema_name FROM information_schema.schemata").fetchall()}
                        if 'marts' in names:
                            return 'marts'
                        if 'mart' in names:
                            return 'mart'
                except Exception:
                    pass
                return s

            pred_schema = _resolve(pred_ro, schema)
            gold_schema = _resolve(gold_ro, schema)

            # Ensure tables exist
            pred_exists = pred_ro.execute(
                f"SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = '{pred_schema}' AND table_name = '{table}'"
            ).fetchone()[0] > 0
            gold_exists = gold_ro.execute(
                f"SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = '{gold_schema}' AND table_name = '{table}'"
            ).fetchone()[0] > 0
            if not pred_exists or not gold_exists:
                logger.debug(f"compare_table: missing table {schema}.{table} pred_exists={pred_exists} gold_exists={gold_exists}")
                pred_ro.close(); gold_ro.close()
                return False

            # Get columns with data types (use gold's type info for numeric detection)
            gold_rows = gold_ro.execute(
                f"SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = '{gold_schema}' AND table_name = '{table}' ORDER BY ordinal_position"
            ).fetchall()
            pred_rows = pred_ro.execute(
                f"SELECT column_name FROM information_schema.columns WHERE table_schema = '{pred_schema}' AND table_name = '{table}' ORDER BY ordinal_position"
            ).fetchall()
            gold_cols = [r[0] for r in gold_rows]
            pred_cols = [r[0] for r in pred_rows]
            gold_types = {r[0]: (r[1] or '').lower() for r in gold_rows}

            # If config specifies compare_cols for this table, restrict to those
            try:
                cfg_layers = self.config.get('layers', {})
                # schema maps to layer name; attempt reverse map
                layer_name = schema if schema in cfg_layers else ('marts' if schema == 'mart' else schema)
                tbl_cfg = cfg_layers.get(layer_name, {}).get('tables', {}).get(table)
                allowed_cols = []
                if isinstance(tbl_cfg, dict):
                    allowed_cols = list(tbl_cfg.get('compare_cols') or [])
                if allowed_cols:
                    # normalize by case-insensitive compare, preserve original casing in gold order
                    gold_map = {c.lower(): c for c in gold_cols}
                    pred_set = {c.lower() for c in pred_cols}
                    inter_cols = [gold_map[a.lower()] for a in allowed_cols if a.lower() in gold_map and a.lower() in pred_set]
                else:
                    # fallback: intersection of gold and pred
                    inter_cols = [c for c in gold_cols if c in pred_cols]
            except Exception:
                inter_cols = [c for c in gold_cols if c in pred_cols]

            # Quick short-circuit if gold has no columns
            if not gold_cols:
                logger.debug(f"compare_table: no gold columns for {schema}.{table}")
                pred_ro.close(); gold_ro.close()
                return False

            if not inter_cols:
                logger.debug(f"compare_table: no intersection columns for {schema}.{table}; gold_cols={gold_cols} pred_cols={pred_cols}")
                pred_ro.close(); gold_ro.close()
                return False

            # Row count short-circuit
            try:
                pred_count = pred_ro.execute(f"SELECT COUNT(*) FROM {pred_schema}.{table}").fetchone()[0]
                gold_count = gold_ro.execute(f"SELECT COUNT(*) FROM {gold_schema}.{table}").fetchone()[0]
                if pred_count != gold_count:
                    logger.debug(f"compare_table: row count mismatch for {schema}.{table}: pred={pred_count} gold={gold_count}")
                    pred_ro.close(); gold_ro.close()
                    return False
            except Exception as e:
                logger.debug(f"compare_table: row count check error for {schema}.{table}: {e}")
                pred_ro.close(); gold_ro.close()
                return False

            pred_ro.close(); gold_ro.close()

            # Strict hash-based comparison on intersection columns (no numeric tolerance).
            col_expr_parts = []
            for c in inter_cols:
                # Cast to string, trim, lower for case-insensitive; treat NULL as literal 'null'
                col_expr_parts.append(f"COALESCE(LOWER(TRIM(CAST({c} AS VARCHAR))), 'null')")
            col_expr = ", ".join(col_expr_parts)

            # Queries to compute (hash, count) per DB
            pred_query = f"SELECT MD5(CONCAT_WS('|', {col_expr})) AS rh, COUNT(*) AS cnt FROM {pred_schema}.{table} GROUP BY rh"
            gold_query = f"SELECT MD5(CONCAT_WS('|', {col_expr})) AS rh, COUNT(*) AS cnt FROM {gold_schema}.{table} GROUP BY rh"

            # Helper to run a query with timeout and return dict(rh->cnt)
            import signal
            class _Timeout(Exception):
                pass
            def run_with_timeout(conn, query, timeout_seconds=300):
                def handler(signum, frame):
                    raise _Timeout()
                old = None
                try:
                    if hasattr(signal, 'SIGALRM'):
                        old = signal.signal(signal.SIGALRM, handler)
                        signal.alarm(timeout_seconds)
                    rows = conn.execute(query).fetchall()
                    return {r[0]: int(r[1]) for r in rows}
                finally:
                    if hasattr(signal, 'SIGALRM'):
                        signal.alarm(0)
                        if old:
                            signal.signal(signal.SIGALRM, old)

            # Open connections and fetch grouped hashes
            pconn = duckdb.connect(str(self.pred_db), read_only=True)
            gconn = duckdb.connect(str(self.gold_db), read_only=True)
            try:
                pred_hash_counts = run_with_timeout(pconn, pred_query)
                gold_hash_counts = run_with_timeout(gconn, gold_query)
            except _Timeout:
                logger.debug(f"compare_table: timeout when hashing {schema}.{table}")
                try:
                    pconn.close(); gconn.close()
                except Exception:
                    pass
                return False
            except Exception as e:
                logger.debug(f"compare_table: error when hashing {schema}.{table}: {e}")
                try:
                    pconn.close(); gconn.close()
                except Exception:
                    pass
                return False

            # Close DB connections
            try:
                pconn.close(); gconn.close()
            except Exception:
                pass

            # Compare dictionaries; if mismatch, compute diagnostic counts
            if pred_hash_counts == gold_hash_counts:
                return True
            else:
                # compute total differing rows
                all_keys = set(pred_hash_counts.keys()) | set(gold_hash_counts.keys())
                diff_rows = sum(abs(pred_hash_counts.get(k,0) - gold_hash_counts.get(k,0)) for k in all_keys)
                logger.debug(f"compare_table: hash-count mismatch for {schema}.{table}: differing_rows={diff_rows} pred_unique_hashes={len(pred_hash_counts)} gold_unique_hashes={len(gold_hash_counts)}")
                return False

        except Exception as e:
            logger.debug(f"compare_table: unexpected error for {schema}.{table}: {e}")
            return False

    def _get_schema_tables(self, db_path: Path, schema_name: str) -> List[str]:
        try:
            conn = duckdb.connect(str(db_path), read_only=True)
            # Resolve mart/marts alias for enumeration
            try:
                if schema_name in ('mart', 'marts'):
                    names = {r[0] for r in conn.execute("SELECT schema_name FROM information_schema.schemata").fetchall()}
                    if 'marts' in names:
                        schema_name = 'marts'
                    elif 'mart' in names:
                        schema_name = 'mart'
            except Exception:
                pass
            rows = conn.execute(
                f"SELECT table_name FROM information_schema.tables WHERE table_schema = '{schema_name}'"
            ).fetchall()
            conn.close()
            return [r[0] for r in rows]
        except Exception:
            return []

    def evaluate_all_tables(self, schemas: List[str]) -> Dict[str, Any]:
        """Return overall_match, schema_results, table_results, totals across schemas."""
        results = {
            "overall_match": True,
            "schema_results": {},
            "table_results": {},
            "total_tables": 0,
            "matching_tables": 0,
        }
        for layer in schemas:
            schema = map_schema(layer)
            gold_tables = set(self._get_schema_tables(self.gold_db, schema))
            pred_tables = set(self._get_schema_tables(self.pred_db, schema))
            missing = list(gold_tables - pred_tables)
            extra = list(pred_tables - gold_tables)
            common = sorted(gold_tables & pred_tables)
            data_matches: Dict[str, bool] = {}
            for t in common:
                ok = self.compare_table(schema, t)
                data_matches[t] = ok
                results["table_results"][f"{schema}.{t}"] = ok
                results["total_tables"] += 1
                if ok:
                    results["matching_tables"] += 1
                else:
                    results["overall_match"] = False
            if missing or extra:
                results["overall_match"] = False
            results["schema_results"][schema] = {
                "tables_match": (not missing and not extra),
                "missing_tables": missing,
                "extra_tables": extra,
                "data_matches": data_matches,
            }
        return results

# ----------------------
# Progressive evaluator (flow)
# ----------------------

class ProgressiveEvaluator:
    """Progressive layer evaluation with pred/gold existence and comparison."""

    def __init__(self, pred_dir: Path, gold_dir: Path, config: Dict, database_file: str):
        self.pred_dir = pred_dir
        self.gold_dir = gold_dir
        self.config = config
        self.database_file = database_file
        self.pred_db_path = self.pred_dir / self.database_file
        self.gold_db_path = self.gold_dir / self.database_file

    def evaluate_all_layers(self) -> Tuple[float, List[Dict[str, Any]]]:
        layers = list(self.config.get("layers", {}).keys())
        layer_results: List[Dict[str, Any]] = []
        scores: List[Tuple[float, float]] = []  # (score, weight)
        for layer_name in layers:
            detail = self._layer_detail(layer_name)
            layer_results.append(detail)
            w = self.config["layers"].get(layer_name, {}).get("weight", 0)
            scores.append((detail["layer_score"], float(w)))
        final_score = weighted_score(scores)
        return final_score, layer_results

    def _layer_detail(self, layer_name: str) -> Dict[str, Any]:
        tables_cfg: Dict[str, Any] = self.config.get("layers", {}).get(layer_name, {}).get("tables", {})
        table_names = list(tables_cfg.keys())
        schema_hint = map_schema(layer_name)
        pred_exec: Dict[str, bool] = {}
        gold_exec: Dict[str, bool] = {}
        comparison: Dict[str, bool] = {}
        def _tbl_weight(val: Any) -> int:
            return int(val) if not isinstance(val, dict) else int(val.get('weight', 0))
        total_points = sum(_tbl_weight(v) for v in tables_cfg.values())
        earned_points = 0
        evaluator = CoreAccuracyEvaluator(self.pred_db_path, self.gold_db_path, self.config)
        try:
            pred_conn = duckdb.connect(str(self.pred_db_path), read_only=True)
            gold_conn = duckdb.connect(str(self.gold_db_path), read_only=True)
        except Exception:
            pred_conn = gold_conn = None
        # Resolve schema aliases per-connection
        def _resolve(conn, s: str) -> str:
            try:
                if s in ('mart', 'marts'):
                    names = {r[0] for r in conn.execute("SELECT schema_name FROM information_schema.schemata").fetchall()}
                    if 'marts' in names:
                        return 'marts'
                    if 'mart' in names:
                        return 'mart'
            except Exception:
                pass
            return s
        pred_schema = _resolve(pred_conn, schema_hint) if pred_conn else schema_hint
        gold_schema = _resolve(gold_conn, schema_hint) if gold_conn else schema_hint
        for t in table_names:
            pred_exists = False
            gold_exists = False
            if pred_conn:
                try:
                    pred_exists = pred_conn.execute(
                        f"SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = '{pred_schema}' AND table_name = '{t}'"
                    ).fetchone()[0] > 0
                except Exception:
                    pred_exists = False
            if gold_conn:
                try:
                    gold_exists = gold_conn.execute(
                        f"SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = '{gold_schema}' AND table_name = '{t}'"
                    ).fetchone()[0] > 0
                except Exception:
                    gold_exists = False
            pred_exec[t] = pred_exists
            gold_exec[t] = gold_exists
            ok = False
            if pred_exists and gold_exists:
                ok = evaluator.compare_table(schema_hint, t)
            comparison[t] = ok
            if ok:
                tv = tables_cfg.get(t, 0)
                earned_points += (int(tv) if not isinstance(tv, dict) else int(tv.get('weight', 0)))
        if pred_conn:
            pred_conn.close()
        if gold_conn:
            gold_conn.close()
        layer_score = (earned_points / total_points) if total_points > 0 else 0.0
        return {
            "layer_name": layer_name,
            "pred_execution": pred_exec,
            "gold_execution": gold_exec,
            "comparison_results": comparison,
            "total_points": total_points,
            "earned_points": earned_points,
            "layer_score": layer_score,
            "layer_weight": self.config.get("layers", {}).get(layer_name, {}).get("weight", 0),
        }

# ----------------------
# CS evaluator (mode)
# ----------------------

class CSEvaluator:
    """CS mode: reuse a single hybrid DB where non-target tables remain gold.

    Flow:
      - Process layers in staging -> intermediate -> marts/mart order
      - Maintain one hybrid DuckDB cloned from gold; attach the original gold DB read-only
      - Before executing a prediction SQL, restore all lower layers and peer tables to gold copies
      - SQL filenames come from the evaluation config (tables.* entries may override via sql_name)
      - Replace only the target table with prediction output, compare vs. gold with CoreAccuracyEvaluator,
        then restore that table to gold before moving on (compare_cols logic is shared with cfs)
    """

    def __init__(self, pred_dir: Path, gold_dir: Path, config: Dict, database_file: str, sql_timeout: int = 300):
        self.pred_dir = pred_dir
        self.gold_dir = gold_dir
        self.config = config
        self.database_file = database_file
        self.gold_db = self.gold_dir / self.database_file
        self.sql_timeout = sql_timeout

    def _schema_for_layer(self, layer: str) -> str:
        return map_schema(layer)

    def _table_entry(self, layer: str, table: str) -> Any:
        return self.config.get('layers', {}).get(layer, {}).get('tables', {}).get(table, {})

    def _sql_name_for_table(self, layer: str, table: str) -> str:
        entry = self._table_entry(layer, table)
        if isinstance(entry, dict):
            return entry.get('sql_name') or table
        return table

    def _read_sql(self, dir_path: Path, layer: str, table: str) -> str:
        sql_name = self._sql_name_for_table(layer, table)
        p = dir_path / 'sql' / layer / f'{sql_name}.sql'
        if not p.exists():
            return ''
        return p.read_text(encoding='utf-8')

    def _process_sql(self, sql: str, layer: str, schema_name: str = None) -> str:
        import re
        if not sql:
            return ''
        # If any explicit schema-qualified FROM exists, keep as-is (just trim)
        if re.search(r"\bfrom\s+\w+\.\w+", sql, re.IGNORECASE):
            return sql.strip().rstrip(';')
        schema = schema_name or self._schema_for_layer(layer)
        s = sql
        # Prefix common layer-local table name patterns when schema is omitted
        s = re.sub(r"\bfrom\s+(stg_[\w_]+__[\w_]+)\b", fr"from {schema}.\\1", s, flags=re.IGNORECASE)
        s = re.sub(r"\bjoin\s+(stg_[\w_]+__[\w_]+)\b", fr"join {schema}.\\1", s, flags=re.IGNORECASE)
        s = re.sub(r"\bfrom\s+(int_[\w_]+__[\w_]+)\b", fr"from {schema}.\\1", s, flags=re.IGNORECASE)
        s = re.sub(r"\bjoin\s+(int_[\w_]+__[\w_]+)\b", fr"join {schema}.\\1", s, flags=re.IGNORECASE)
        # Marts layer tables often use lever__ prefix
        s = re.sub(r"\bfrom\s+(lever__[\w_]+)\b", fr"from {schema}.\\1", s, flags=re.IGNORECASE)
        s = re.sub(r"\bjoin\s+(lever__[\w_]+)\b", fr"join {schema}.\\1", s, flags=re.IGNORECASE)
        s = s.strip().rstrip(';')
        return s

    def _exec_sql_safely(self, conn: duckdb.DuckDBPyConnection, sql: str) -> bool:
        if not sql:
            return False
        import signal
        class _Timeout(Exception):
            pass
        def handler(signum, frame):
            raise _Timeout()
        old = None
        try:
            if hasattr(signal, 'SIGALRM'):
                old = signal.signal(signal.SIGALRM, handler)
                signal.alarm(self.sql_timeout)
            conn.execute(sql)
            return True
        except Exception:
            return False
        finally:
            if hasattr(signal, 'SIGALRM'):
                signal.alarm(0)
                if old:
                    signal.signal(signal.SIGALRM, old)

    def _resolve_schema_name(self, conn: duckdb.DuckDBPyConnection, layer: str) -> str:
        schema_hint = self._schema_for_layer(layer)
        try:
            names = {row[0] for row in conn.execute("SELECT schema_name FROM information_schema.schemata").fetchall()}
            if schema_hint in names:
                return schema_hint
            if schema_hint == 'mart' and 'marts' in names:
                return 'marts'
            if schema_hint == 'marts' and 'mart' in names:
                return 'mart'
        except Exception:
            pass
        return schema_hint

    def _table_weight(self, cfg_value: Any) -> int:
        if isinstance(cfg_value, dict):
            return int(cfg_value.get('weight', 0))
        return int(cfg_value)

    def _list_tables(self, conn: duckdb.DuckDBPyConnection, schema: str) -> set:
        if not conn or not schema:
            return set()
        try:
            rows = conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = ?",
                (schema,),
            ).fetchall()
            return {r[0] for r in rows}
        except Exception:
            return set()

    def _attach_gold_alias(self, conn: duckdb.DuckDBPyConnection) -> str:
        alias = "gold_cs_ref"
        try:
            path = str(self.gold_db).replace("'", "''")
            conn.execute(f"ATTACH DATABASE '{path}' AS {alias} (READ_ONLY)")
            return alias
        except Exception:
            return ""

    def _detach_gold_alias(self, conn: duckdb.DuckDBPyConnection, alias: str) -> None:
        if not alias:
            return
        try:
            conn.execute(f"DETACH DATABASE {alias}")
        except Exception:
            pass

    def _copy_table_from_gold(self, conn: duckdb.DuckDBPyConnection, schema: str, table: str, alias: str, available: set) -> bool:
        if not schema or not alias:
            return False
        try:
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
            if alias and table in available:
                conn.execute(
                    f"CREATE OR REPLACE TABLE {schema}.{table} AS SELECT * FROM {alias}.{schema}.{table}"
                )
                return True
            conn.execute(f"DROP TABLE IF EXISTS {schema}.{table}")
            return False
        except Exception:
            return False

    def _restore_layer_tables(
        self,
        conn: duckdb.DuckDBPyConnection,
        layer: str,
        schema: str,
        alias: str,
        available: set,
        *,
        skip_table: str = None,
    ) -> None:
        tables_cfg = self.config.get('layers', {}).get(layer, {}).get('tables', {})
        for tbl in tables_cfg.keys():
            if skip_table and tbl == skip_table:
                continue
            self._copy_table_from_gold(conn, schema, tbl, alias, available)

    def _ensure_gold_dependencies(
        self,
        conn: duckdb.DuckDBPyConnection,
        current_layer: str,
        target_table: str,
        alias: str,
        layer_schemas: Dict[str, str],
        layer_tables: Dict[str, set],
        ordered_layers: List[str],
    ) -> None:
        if not alias:
            return
        idx = ordered_layers.index(current_layer)
        for lower in ordered_layers[:idx]:
            schema = layer_schemas.get(lower)
            available = layer_tables.get(lower, set())
            self._restore_layer_tables(conn, lower, schema, alias, available)
        schema = layer_schemas.get(current_layer)
        available = layer_tables.get(current_layer, set())
        self._restore_layer_tables(conn, current_layer, schema, alias, available, skip_table=target_table)

    def _build_pred_table(self, conn: duckdb.DuckDBPyConnection, layer: str, table: str, schema: str) -> bool:
        raw_sql = self._read_sql(self.pred_dir, layer, table)
        sql = self._process_sql(raw_sql, layer, schema)
        if not sql:
            return False
        try:
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        except Exception:
            return False
        create_sql = f"CREATE OR REPLACE TABLE {schema}.{table} AS ({sql})"
        return self._exec_sql_safely(conn, create_sql)

    def _ordered_layers(self) -> List[str]:
        configured = list(self.config.get('layers', {}).keys())
        priority = ['staging', 'intermediate', 'marts', 'mart']
        ordered: List[str] = [layer for layer in priority if layer in configured]
        ordered += [layer for layer in configured if layer not in ordered]
        return ordered

    def evaluate_all_layers(self) -> Tuple[float, List[Dict[str, Any]]]:
        import shutil

        ordered_layers = self._ordered_layers()
        if not ordered_layers:
            return 0.0, []

        temp_dir = self.pred_dir / "tmp"
        shutil.rmtree(temp_dir, ignore_errors=True)
        try:
            temp_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            return 0.0, []

        hybrid_db = temp_dir / "cs_hybrid.duckdb"
        try:
            shutil.copy2(self.gold_db, hybrid_db)
        except Exception:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return 0.0, []

        layer_results: List[Dict[str, Any]] = []
        scores: List[Tuple[float, float]] = []

        def _open_hybrid_conn():
            try:
                conn = duckdb.connect(str(hybrid_db))
                alias = self._attach_gold_alias(conn)
                return conn, alias
            except Exception:
                return None, ""

        def _close_hybrid_conn(conn, alias):
            if conn:
                self._detach_gold_alias(conn, alias)
                conn.close()

        hybrid_conn, gold_alias = _open_hybrid_conn()
        if not hybrid_conn:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return 0.0, []

        try:
            gold_conn = duckdb.connect(str(self.gold_db), read_only=True)
        except Exception:
            gold_conn = None
        layer_schemas: Dict[str, str] = {}
        layer_tables: Dict[str, set] = {}
        if gold_conn:
            for layer in ordered_layers:
                schema = self._resolve_schema_name(gold_conn, layer)
                if not schema:
                    schema = self._schema_for_layer(layer)
                layer_schemas[layer] = schema
                layer_tables[layer] = self._list_tables(gold_conn, schema)
        else:
            for layer in ordered_layers:
                layer_schemas[layer] = self._schema_for_layer(layer)
                layer_tables[layer] = set()

        evaluator = CoreAccuracyEvaluator(
            hybrid_db, self.gold_db, self.config
        )

        try:
            for layer in ordered_layers:
                tables_cfg = self.config.get('layers', {}).get(layer, {}).get('tables', {})
                table_names = list(tables_cfg.keys())
                total_points = sum(self._table_weight(v) for v in tables_cfg.values())
                earned_points = 0
                pred_exec: Dict[str, bool] = {}
                comparison: Dict[str, bool] = {}
                gold_exec: Dict[str, bool] = {}
                schema = layer_schemas.get(layer) or self._schema_for_layer(layer)
                gold_tables = layer_tables.get(layer, set())
                for t in table_names:
                    gold_exec[t] = t in gold_tables

                for table in table_names:
                    self._ensure_gold_dependencies(
                        hybrid_conn,
                        layer,
                        table,
                        gold_alias,
                        layer_schemas,
                        layer_tables,
                        ordered_layers,
                    )
                    ok_pred = self._build_pred_table(hybrid_conn, layer, table, schema)
                    pred_exec[table] = ok_pred
                    _close_hybrid_conn(hybrid_conn, gold_alias)
                    match = False
                    if ok_pred:
                        try:
                            match = evaluator.compare_table(schema, table)
                        except Exception:
                            match = False
                    comparison[table] = match
                    if match:
                        earned_points += self._table_weight(tables_cfg.get(table, 0))
                    hybrid_conn, gold_alias = _open_hybrid_conn()
                    if not hybrid_conn:
                        raise RuntimeError("Failed to reopen hybrid database for CS evaluation")
                    self._copy_table_from_gold(hybrid_conn, schema, table, gold_alias, gold_tables)

                layer_score = (earned_points / total_points) if total_points > 0 else 0.0
                layer_weight = self.config.get('layers', {}).get(layer, {}).get('weight', 0)
                layer_results.append({
                    'layer_name': layer,
                    'pred_execution': pred_exec,
                    'gold_execution': gold_exec,
                    'comparison_results': comparison,
                    'total_points': total_points,
                    'earned_points': earned_points,
                    'layer_score': layer_score,
                    'layer_weight': layer_weight,
                })
                scores.append((layer_score, float(layer_weight)))

            final_score = weighted_score(scores)
            return final_score, layer_results
        finally:
            if gold_conn:
                gold_conn.close()
            _close_hybrid_conn(hybrid_conn, gold_alias)
            shutil.rmtree(temp_dir, ignore_errors=True)

# ----------------------
# Pipeline evaluator
# ----------------------

class PipelineEvaluator:
    """Top-level evaluator: threshold, core accuracy, and selected mode."""

    def __init__(self, config_path: str, force_rebuild: bool = False, mode: str = "cfs"):
        self.config = yaml.safe_load(open(config_path, 'r', encoding='utf-8'))
        self.force_rebuild = force_rebuild
        self.mode = mode

    def evaluate_example(self, example_id: str, gold_dir: str, pred_dir: str) -> Dict[str, Any]:
        config_examples = self.config.get("examples", {})
        cfg_id, err = resolve_example_id(example_id, config_examples)
        if err:
            return {"error": err, "final_score": 0}
        example_config = config_examples.get(cfg_id)
        # Use config id for gold and the provided id for pred so prediction dirs can have suffixes while gold stays the base name
        gold_path = Path(gold_dir) / cfg_id
        pred_path = Path(pred_dir) / example_id
        if not gold_path.exists() or not pred_path.exists():
            return {"error": "Directory not found", "final_score": 0}
        database_file = example_config.get("database_file", "database.duckdb")
        expected_schemas = list(example_config.get("layers", {}).keys()) or ["staging", "intermediate", "marts"]

        # Threshold
        run_ok = execute_run_py(pred_path, database_file, force_rebuild=self.force_rebuild)
        schemas_ok = validate_schemas(pred_path / database_file, expected_schemas) if run_ok else False
        threshold_info = {
            "run_py_success": run_ok,
            "schemas_valid": schemas_ok,
            "threshold_passed": run_ok and schemas_ok,
            "error_messages": ([] if (run_ok and schemas_ok) else ["run.py failed or schemas missing"]),
        }

        pred_db = pred_path / database_file
        gold_db = gold_path / database_file
        core_eval = CoreAccuracyEvaluator(pred_db, gold_db)
        core_info = core_eval.evaluate_all_tables(expected_schemas)

        # Core-perfect short-circuit to 100
        if core_info.get("overall_match", False):
            return {
                "example_id": example_id,
                "task_type": "DE",
                "evaluation_mode": self.mode,
                "threshold_evaluation": threshold_info,
                "core_accuracy_evaluation": core_info,
                "partial_evaluation": {
                    "layer_results": [],
                    "summary": {
                        "total_layers": 0,
                        "perfect_layers": 0,
                        "partially_correct_layers": 0,
                        "failed_layers": 0,
                        "layer_scores": {},
                    },
                },
                "final_score": 100.0,
                "evaluation_level": "core_perfect_match",
                "timestamp": datetime.now().isoformat(),
            }

        # Non-perfect: run selected mode
        if self.mode == "cs":
            cs_eval = CSEvaluator(pred_path, gold_path, example_config, database_file)
            final_score, layer_results = cs_eval.evaluate_all_layers()
            summary = build_summary(layer_results)
            return {
                "example_id": example_id,
                "task_type": "DE",
                "evaluation_mode": "cs",
                "threshold_evaluation": threshold_info,
                "core_accuracy_evaluation": core_info,
                "partial_evaluation": {"layer_results": layer_results, "summary": summary},
                "final_score": final_score,
                "evaluation_level": "partial_evaluation",
                "timestamp": datetime.now().isoformat(),
            }
        else:
            # cfs: use progressive flow
            prog_eval = ProgressiveEvaluator(pred_path, gold_path, example_config, database_file)
            final_score, layer_results = prog_eval.evaluate_all_layers()
            summary = build_summary(layer_results)
            return {
                "example_id": example_id,
                "task_type": "DE",
                "evaluation_mode": "cfs",
                "threshold_evaluation": threshold_info,
                "core_accuracy_evaluation": core_info,
                "partial_evaluation": {"layer_results": layer_results, "summary": summary},
                "final_score": final_score,
                "evaluation_level": "partial_evaluation",
                "timestamp": datetime.now().isoformat(),
            }

# ----------------------
# Batch evaluation
# ----------------------

def _sanitize_segment(value: str, fallback: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        return fallback
    for ch in ("/", "\\"):
        cleaned = cleaned.replace(ch, "_")
    cleaned = cleaned.replace("..", "_")
    return cleaned or fallback


def _parse_model_and_param(pred_dir: str) -> Tuple[str, str]:
    """Infer model + param tag from prediction directory name."""
    path_obj = Path(pred_dir).expanduser()
    name = path_obj.name or path_obj.parent.name
    marker = "_maxiter_"
    if marker in name:
        prefix, suffix = name.split(marker, 1)
        model = prefix.rstrip("_-")
        param_tag = f"maxiter_{suffix}"
    else:
        model = name
        param_tag = "default"
    return _sanitize_segment(model, "unknown_model"), _sanitize_segment(param_tag, "default")


def _infer_task_from_examples(example_ids: List[str]) -> str:
    """Derive task (impl/evol) from example ids; fall back to mixed/unknown."""
    tasks = set()
    for example_id in example_ids:
        lowered = example_id.lower()
        if "impl" in lowered:
            tasks.add("impl")
        if "evol" in lowered:
            tasks.add("evol")
    if len(tasks) == 1:
        return tasks.pop()
    if len(tasks) > 1:
        return "mixed"
    return "unknown"

# ----------------------
# Example id resolution
# ----------------------

def resolve_example_id(requested_id: str, configured: Dict[str, Any]) -> Tuple[str, str]:
    """
    Resolve the config example id for a requested id.

    Rules:
      1) Exact match wins.
      2) Otherwise, if requested_id starts with a configured id (no delimiter required) and that match is unique, use that config id.
      3) If multiple configured ids satisfy the prefix rule, return an ambiguity error.
    Returns (config_id, error_message). On success, error_message is "".
    """
    if requested_id in configured:
        return requested_id, ""
    candidates = [cfg for cfg in configured.keys() if requested_id.startswith(cfg)]
    if len(candidates) == 1:
        return candidates[0], ""
    if len(candidates) > 1:
        return "", f"Example id '{requested_id}' matches multiple configured prefixes: {candidates}"
    return "", f"Example not configured: {requested_id}"


def _prepare_output_paths(base_dir: str, *, model: str, task: str, param_tag: str, mode: str) -> Tuple[Path, Path]:
    """
    Create output under <base_dir>/<model>/<task>/<param_tag>/<mode>/summary.json|scores.csv.

    Path segments are sanitized to avoid accidental traversal or OS-specific separators.
    """
    model_seg = _sanitize_segment(model, "unknown_model")
    task_seg = _sanitize_segment(task, "unknown_task")
    param_seg = _sanitize_segment(param_tag, "default")
    mode_seg = _sanitize_segment(mode, "unknown_mode")

    run_root = Path(base_dir).expanduser() / model_seg / task_seg / param_seg / mode_seg
    run_root.mkdir(parents=True, exist_ok=True)
    return run_root / "summary.json", run_root / "scores.csv"


def batch_evaluate(config_path: str, gold_dir: str, pred_dir: str, example_ids: List[str] = None, output_dir: str = "results", *, force_rebuild: bool = False, mode: str = "cfs") -> Dict:
    evaluator = PipelineEvaluator(config_path, force_rebuild=force_rebuild, mode=mode)
    if not example_ids:
        config_examples = evaluator.config.get("examples", {})
        available = [d.name for d in Path(pred_dir).iterdir() if d.is_dir()]
        resolved: List[str] = []
        for avail in available:
            cfg_id, err = resolve_example_id(avail, config_examples)
            if err:
                print(f"[skip] {avail}: {err}")
                continue
            resolved.append(avail)
        example_ids = resolved

    results: Dict[str, Any] = {}
    summary_rows: List[Dict[str, Any]] = []

    for i, example_id in enumerate(example_ids, 1):
        print(f"[{i}/{len(example_ids)}] {example_id}")
        try:
            r = evaluator.evaluate_example(example_id, gold_dir, pred_dir)
            r["task_type"] = "DE"
            results[example_id] = r
            summary_rows.append({"example_id": example_id, "final_score": float(r.get("final_score", 0))})
        except Exception as e:
            print(f"  -> Error: {e}")
            results[example_id] = {"example_id": example_id, "task_type": "DE", "final_score": 0, "error": str(e)}
            summary_rows.append({"example_id": example_id, "final_score": 0.0})

    total = len(summary_rows)
    perfect = sum(1 for s in summary_rows if s["final_score"] == 100)
    failed = sum(1 for s in summary_rows if s["final_score"] == 0)
    partial = total - perfect - failed
    avg = (sum(s["final_score"] for s in summary_rows) / total) if total else 0.0

    evaluation_summary = {
        "total_examples": total,
        "perfect_scores": perfect,
        "partial_scores": partial,
        "failed_examples": failed,
        "average_score": avg,
        "evaluation_mode": mode,
        "task_type_summary": {"DE": {"count": total, "average_score": avg, "total_score": sum(s["final_score"] for s in summary_rows)}},
    }

    example_order = [row["example_id"] for row in summary_rows]
    model_name, param_tag = _parse_model_and_param(pred_dir)
    task_name = _infer_task_from_examples(example_ids)
    json_file, csv_file = _prepare_output_paths(output_dir, model=model_name, task=task_name, param_tag=param_tag, mode=mode)

    payload = {"evaluation_summary": evaluation_summary, "example_results": results, "example_order": example_order}
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    df_rows = [{"task": row["example_id"], "score": f"{row['final_score']:.2f}"} for row in summary_rows]
    df_rows.append({"task": "overall-average", "score": f"{avg:.2f}"})
    df = pd.DataFrame(df_rows)
    df.to_csv(csv_file, index=False)

    print(f"Saved: {json_file}\nSaved: {csv_file}")
    return payload

__all__ = [
    "execute_run_py",
    "validate_schemas",
    "CoreAccuracyEvaluator",
    "ProgressiveEvaluator",
    "CSEvaluator",
    "PipelineEvaluator",
    "batch_evaluate",
]
