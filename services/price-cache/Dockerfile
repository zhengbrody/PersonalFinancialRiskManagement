# services/price-cache/Dockerfile
# Build context is REPO ROOT.
FROM public.ecr.aws/lambda/python:3.11

COPY services/price-cache/requirements.txt ${LAMBDA_TASK_ROOT}/requirements.txt
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

COPY libs/ ${LAMBDA_TASK_ROOT}/libs/
COPY services/price-cache/handler.py ${LAMBDA_TASK_ROOT}/

CMD ["handler.lambda_handler"]
