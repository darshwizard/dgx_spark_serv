FROM eugr/spark-vllm@sha256:431593a0a7064bd41d9b2720ca5d00185540ce0fdf1e893adf85af9c07dc7175
COPY tool-eval-bench /opt/tool-eval-bench
COPY llama-benchy /opt/llama-benchy
RUN pip install --no-deps /opt/tool-eval-bench /opt/llama-benchy && python3 -m tool_eval_bench --help && python3 -m llama_benchy --help
