FROM nvcr.io/nvidia/vllm@sha256:cb38bbefdbc3e9fe045f931dd72cbd58cd48985c7e09916bcc6c15c10f39b929
COPY tool-eval-bench /opt/tool-eval-bench
COPY llama-benchy /opt/llama-benchy
RUN pip install --no-deps /opt/tool-eval-bench /opt/llama-benchy && python3 -m tool_eval_bench --help && python3 -m llama_benchy --help
