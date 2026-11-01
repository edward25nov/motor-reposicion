FROM apache/airflow:3.3.2-python3.12

# git: commit en los manifest y repositorio para DVC. El repositorio montado pertenece a otro
# usuario del host, así que se marca como seguro.
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && git config --system --add safe.directory '*'
USER airflow

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir "apache-airflow==3.3.2" -r /tmp/requirements.txt "dvc==3.67.1"
