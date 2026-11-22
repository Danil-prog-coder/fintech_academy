FROM python:3.13-slim
ENV PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=10
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    TIKTOKEN_CACHE_DIR=/opt/tiktoken QUESTION_FALLBACK_CACHE_DIR=/opt/models
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
# The chunker's tokenizer is downloaded once at build time: the running service needs no access to its CDN.
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')" || echo "WARNING: tiktoken encoding not cached, approximate counts"
# Optional local fallback embedder of the question analytics (BAAI/bge-m3 ONNX, ~2.2 GB):
# --build-arg PRELOAD_FALLBACK_EMBEDDER=1 and QUESTION_FALLBACK_EMBEDDER=BAAI/bge-m3 in .env.
ARG PRELOAD_FALLBACK_EMBEDDER=0
RUN if [ "$PRELOAD_FALLBACK_EMBEDDER" = "1" ]; then python -c "from fastembed import TextEmbedding; \
from fastembed.common.model_description import ModelSource, PoolingType; \
TextEmbedding.add_custom_model(model='BAAI/bge-m3', pooling=PoolingType.CLS, normalization=True, sources=ModelSource(hf='BAAI/bge-m3'), \
dim=1024, model_file='onnx/model.onnx', additional_files=['onnx/model.onnx_data']); \
m = TextEmbedding('BAAI/bge-m3', cache_dir='/opt/models'); print(len(list(m.embed(['проверка']))[0]))" || echo "WARNING: bge-m3 preload failed"; fi
COPY rag_service ./rag_service
COPY prompts ./prompts
COPY config ./config
COPY data ./data
RUN useradd --system --uid 10003 rag && mkdir -p /app/var && chown -R rag /app/var /app/data
USER rag
# var/ (state, uploads, Qdrant local mode) is a volume
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --retries=5 CMD python -c "import os,urllib.request;urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get('API_PORT','8080')}/health\",timeout=4)" || exit 1
CMD ["sh", "-c", "uvicorn rag_service.api.app:app --host 0.0.0.0 --port ${API_PORT:-8080}"]
