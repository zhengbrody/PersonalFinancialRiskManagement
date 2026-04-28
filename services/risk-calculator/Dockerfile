# services/risk-calculator/Dockerfile
#
# Container Image Lambda (per ADR-0002): 250 MB zip cap is broken by
# numpy/scipy/pandas combined. Container path lifts the cap to 10 GB
# at the cost of ~50-150 ms extra cold start (negligible here since
# scipy import alone is ~600 ms).
#
# Build context is the REPO ROOT (not this dir) because we need to
# COPY libs/ into the image. CDK DockerImageFunction handles this via
# the `cmd_directory` param; locally:
#     docker build -t risk-calculator -f services/risk-calculator/Dockerfile .
#
# x86_64 base because Phase 1 EC2 picked x86_64 — keeping arch matched
# until Phase 4 cost-optimization sweep evaluates Graviton.
FROM public.ecr.aws/lambda/python:3.11

# Install deps first for layer caching — requirements.txt is more stable
# than the source code, so this layer hits the cache on most builds.
COPY services/risk-calculator/requirements.txt ${LAMBDA_TASK_ROOT}/requirements.txt
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

# Now the source: shared library + this service's handler
COPY libs/ ${LAMBDA_TASK_ROOT}/libs/
COPY services/risk-calculator/handler.py ${LAMBDA_TASK_ROOT}/

# Lambda runtime expects a "module.handler_function" string
CMD ["handler.lambda_handler"]
