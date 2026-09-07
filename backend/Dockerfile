FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

# scipy·pandas·scikit-learn 은 휠이 수십 MB라 회선이 느리면 기본 타임아웃(15초)에 걸린다.
# 실제로 t4g.micro 에서 빌드하다 TimeoutError 로 죽는 걸 봤다. 넉넉히 주고 재시도한다.
RUN pip install --no-cache-dir --timeout 120 --retries 5 -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
