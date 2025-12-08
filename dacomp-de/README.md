# DAComp-DE 💾

This directory contains the DAComp-DE datasets and evaluation code. You only need to run the `dacomp-de/download.py` script to download all datasets.

---

## 1. Requirements ⚙️

* If the datasets require authentication:

  ```bash
  huggingface-cli login
  ```
---

## 2. Download Datasets 📥

In the `dacomp-de/download.py` file, edit the following parts to set the correct `repo_id` and `download_dir`:

* For Chinese tasks data (`tasks_zh`):

  ```python
  repo_id = "DAComp/dacomp-de-zh"
  download_dir = "./tasks_zh"
  ```

* For tasks data (`tasks`):

  ```python
  repo_id = "DAComp/dacomp-de"
  download_dir = "./tasks"
  ```

* For evaluation gold standard data (`evaluation_suite/gold`):

  ```python
  repo_id = "DAComp/dacomp-de-gold"
  download_dir = "./evaluation_suite/gold"
  ```

Run the following command to download the data:

```bash
python download.py
```

After downloading, unzip the `.zip` files into the respective directories:

```bash
unzip ./tasks_zh/dacomp-de-zh.zip -d ./tasks_zh
unzip ./tasks/dacomp-de.zip -d ./tasks
unzip ./evaluation_suite/gold/dacomp-de-gold.zip -d ./evaluation_suite/gold
```

Repeat this process as needed by changing the `repo_id` and `download_dir`. 🔁



---

## 3. Evaluation Scripts 📊

After the data is downloaded, refer to the following READMEs for evaluation:

* **Standard DAComp-DE Tasks**:

  * `dacomp-de/evaluation_suite/README.md`
    This README is used to evaluate **DE-Impl** and **Evol** tasks and supports **cfs** and **cs** evaluation modes.

* **DE-Arch Unified Evaluator**:

  * `dacomp-de/evaluation_suite_arch/README.md`
    This README is used to evaluate **DE-Arch** tasks.

