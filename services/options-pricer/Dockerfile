# services/options-pricer/Dockerfile
# Build context is REPO ROOT.
FROM public.ecr.aws/lambda/python:3.11

COPY services/options-pricer/requirements.txt ${LAMBDA_TASK_ROOT}/requirements.txt
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

COPY libs/ ${LAMBDA_TASK_ROOT}/libs/
COPY services/options-pricer/handler.py ${LAMBDA_TASK_ROOT}/

CMD ["handler.lambda_handler"]
