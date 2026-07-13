FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-chache-dir -r requirements.txt

COPY . .

RUN mkdir -p docs nextec_index

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "--port", "8000"]