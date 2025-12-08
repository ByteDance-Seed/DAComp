# DAComp-DA Data Download Guide


## 1. Prerequisites

```bash
python3 -m pip install -U "huggingface_hub>=0.25" && huggingface-cli login
```

---

## 2. English Tasks (`DAComp/dacomp-da`)

```bash
hf download DAComp/dacomp-da --repo-type dataset --local-dir tasks
```

After the download you should have:

```
tasks/
  ├── dacomp-001/dacomp-001.sqlite
  ├── …
  └── dacomp-da.jsonl
```

---

## 3. Chinese Tasks (`DAComp/dacomp-da-zh`)

```bash
hf download DAComp/dacomp-da-zh --repo-type dataset --local-dir tasks_zh
```

The resulting tree looks like:

```
tasks_zh/
  ├── dacomp-zh-001/dacomp-zh-001.sqlite
  ├── …
  └── dacomp-da-zh.jsonl
```
