FROM python:3.12-slim

WORKDIR /app

# Install dashboard deps
COPY dashboard/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install SDK from source
COPY sdk/ /sdk
RUN pip install -e /sdk

# Copy dashboard source
COPY dashboard/ /app/dashboard

EXPOSE 8501

CMD ["streamlit", "run", "dashboard/app.py", "--server.address=0.0.0.0", "--server.port=8501"]
