# Cura AI Agent

Cura adalah layanan AI Agent untuk verifikasi keaslian obat berbasis YOLO + OCR + RAG.  
Sistem ini memanfaatkan BPOM Database, dan MongoDB Atlas + FAISS untuk melakukan analisis multi-tahap yang cepat, akurat, dan aman.  

---

## Fitur Utama
- Computer Vision (YOLOv8 + OCR) untuk mendeteksi teks dan label dari kemasan obat.  
- RegEx dan BPOM Validation untuk validasi Nomor Izin Edar (NIE).  
- Retrieval-Augmented Generation (RAG) untuk pencarian hybrid dengan FAISS, MongoDB, dan Web Search.  
- Agent Orchestration dengan LLM, error handling, dan logging.  
- Dockerized Deployment untuk dijalankan di VM (GCP) maupun lokal.  
- Logging dan Monitoring dengan audit log, scoring, interactive CLI, dan observability.  

---

## Struktur Project

|   .env
|   .env.example
|   .gitignore
|   docker-compose.yml
|   environment.yml
|   main.py
|   pytest.ini
|   readme.md
|   requirements.txt
|
|
|
+---app
|   |   container.py
|   |   __init__.py
|   |
|   +---application
|   |   |   build_index_job.py
|   |   |   commands.py
|   |   |   retrieve_use_case.py
|   |   |   scan_use_case.py
|   |   |   use_cases.py
|   |   |
|   |   +---stream
|   |       |   rt_worker.py
|   |      
|   |      
|   |             
|   |   
|   |
|   +---domain
|   |   |   confidence.py
|   |   |   detectors.py
|   |   |   models.py
|   |   |   ports.py
|   |   |   scan_entities.py
|   |   |   validators.py
|   |   |
|   |   +---services
|   |       |   verification_aggregator.py
|   |
|   +---infra
|   |   |   container.py
|   |   |
|   |   +---api
|   |   |   |   agent.py
|   |   |   |   deps.py
|   |   |   |   satusehat_adapter.py
|   |   |   |   security.py
|   |   |   |   verify.py
|   |   |   |
|   |   |
|   |   |
|   |   +---llm
|   |   |   |   openai_adapter.py
|   |   |   |   openai_embedder.py
|   |   |   
|   |   |
|   |   +---ocr
|   |   |   |   paddle_adapter.py
|   |   |   |   tesseract_adapter.py
|   |   |   |   tesseract_title_adapter.py
|   |   |   |
|   |   |
|   |   +---pipelines
|   |   |   |   scan_pipeline.py
|   |   |   
|   |   +---regex
|   |   |   |   bpom_validator.py
|   |   |   
|   |   |
|   |   +---repo
|   |   |   |   mongo_repo.py
|   |   |
|   |   +---search
|   |   |   |   faiss_index.py
|   |   |   |   router.py
|   |   |   
|   |   |
|   |   +---vision
|   |   |   |   yolo_detector.py
|   |
|   +---presentation
|   |   |   health.py
|   |   |   routers.py
|   |   |   schemas.py
|   |   |
|   |   +---endpoints
|   |   |   |   detect.py
|   |   |   |   ws_detect.py
|   |   |
|   |   +---routes
|   |   |   |   scan.py
|   |
|   +---services
|       |   agent_orchestrator.py
|       |   guards.py
|       |   medical_classifier.py
|       |   prompt_service.py
|       |   query_parser.py
|       |   session_state.py
|       |   verification_service.py
|       |
|       +---tools
|           |   fetch_tool.py
|           |   guards.py
|           |   search_tool.py
|               __init__.py
|   
|
+---artifacts
|   |   args.yaml
|   |   events.out.tfevents.1755442462.7feef27aa3a6.635.0
|   |   results.csv
|   |
|   \---weights
|           best.pt
|           last.pt
|
+---clients
|       ai_service_client.py
|
+---config
|   |   regex.yaml
|   |
|   \---prompts
|           base_system.md
|           intents.yaml
|
+---crawler
|   |   browser_fetcher.py
|   |   cekbpom_client.py
|   |   cekbpom_detail.py
|   |   cekbpom_json.py
|   |   cekbpom_parsers.py
|   |   ingest.py
|   |
|   +---faiss
|   |       build_index.py
|   |
|   +---jobs
|       |   crawl_categories.py
|       |   crawl_obat.py
|       |   search_terms.py
|       |
|
+---data
|   +---faiss
|   |       ids.npy
|   |       products.index
|   |
|   +---yolo_title
|   |   |   data.yaml
|   |   |
|   |   +---images
|   |   |   +---test
|   |   |   |
|   |   |   +---train
|   |   |   |
|   |   |   \---valid
|   |   |
|   |   \---labels
|   |       |   train.cache
|   |       |   valid.cache
|   |       |
|   |       +---test
|   |       |
|   |       +---train
|   |       |
|   |       \---valid
|   |
|   \---yolo_title_clean
|       |   data.yaml
|       |
|       +---images
|       |   +---test
|       |   |
|       |   +---train
|       |   |
|       |   \---valid
|       |
|       \---labels
|           +---test
|           |
|           +---train
|           |
|           \---valid
|
+---docker
|       Dockerfile.cpu
|       Dockerfile.gpu
|
+---models
|   \---yolo
|           yolo11m.pt
|
+---notebooks
|   |   clean_dataset.py
|   |   yolo11m.pt
|   |   yolo11n.pt
|   |   Yolo_Train.ipynb
|   |
|
+---scripts
|   |   cli_flow_check.py
|   |   debug_dt_sample.py
|   |   interactive_cli.py
|   |   scaffold_scan.sh
|   |   sniff_cekbpom_requests.py
|   |   sniff_click_detail.py
|   |   webcam_scan.py
|   
|
+---tests
|   +---integration
|   |   |   test_scan_route.py
|   |   |   test_verify_route.py
|   |    
|   |
|   \---unit
|       |   test_bpom_validator.py
|       |   test_detectors.py
|       |   test_redis_cache.py
|
+---uploads

---

## Menjalankan Project

### 1. Clone Repository

git clone https://github.com/<username>/AIC-MechaMinds-17.git
cd AIC-MechaMinds-17

### 2. Setup Environment

---

Menggunakan conda:

conda env create -f environment.yml
conda activate medverify

Atau menggunakan pip:

pip install -r requirements.txt

---

### 3. Konfigurasi .env

Salin file contoh:
cp .env.example .env

Isi variabel penting:

OPENAI_API_KEY=your_api_key
MONGO_URI=your_mongo_uri
BPOM_BASE_URL=https://cekbpom.pom.go.id

---

### 4. Menjalankan dengan Docker

docker-compose up --build

### 5. Jalankan Service Lokal

uvicorn main:app --host 0.0.0.0 --port 8000 --reload

---

## Menjalankan FAISS Index

Bangun ulang index FAISS:
python -c "from app.application.build_index_job import run_build; run_build()"

---

## Testing

pytest -v

---

## API Endpoint

* `POST /v1/verify` → Verifikasi teks atau NIE
* `POST /v1/verify-photo` → Verifikasi via foto (YOLO + OCR)
* `POST /v1/agent` → Query AI Agent (LLM + RAG)

---

## Deployment

* Local Development: Conda / Pip + Uvicorn
* Docker: `docker-compose` untuk VM GCP atau server
* Production Ready: gunakan reverse proxy (nginx), TLS/SSL, dan monitoring (Grafana/Prometheus)

---

## Kontributor

* Gabriel Batavia – AI Engineer 
* AIC-MechaMinds-17 Team

---

## Lisensi

Project ini menggunakan lisensi MIT.
Silakan gunakan, modifikasi, dan kembangkan dengan attribution.

