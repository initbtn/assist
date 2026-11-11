# [Python/FastAPI 패턴]: Depends 기반 의존성 역전 및 Lifespan 수명주기 데몬

- **분류**: `backend_architecture`
- **도메인**: `infra_devops`
- **주제**: `Python/FastAPI`
- **제목**: `FastAPI Depends 의존성 주입 및 Lifespan Graceful Shutdown`
- **우선순위**: `critical`

## 규칙 개요
1. **의존성 역전 원칙 (DIP)**: 데이터베이스 세션, 외부 API 클라이언트, 보안 검증은 라우터 내부에서 직접 인스턴스화하지 않고 `FastAPI.Depends`를 통해 주입받아 테스트 시 모킹 및 격리가 가능해야 합니다.
2. **Lifespan 수명주기 관리**: BackgroundTasks는 단일 요청 범위이므로, 서버 전체 수명주기를 함께하는 백그라운드 데몬(유휴 감시, 큐 워커 등)은 반드시 `@asynccontextmanager`의 `lifespan(app: FastAPI)`에서 시작하고 서버 종료 시 `task.cancel()`로 정상 취소(Graceful Shutdown)해야 합니다.

---

### ❌ Anti-Pattern (Bad)

```python
# app/main.py
# [결함]: 라우터 함수 내부에서 직접 DB 인스턴스 생성, 백그라운드 태스크 무방비 생성으로 종료 시 좀비 프로세스/누수 유발.
import asyncio
from fastapi import FastAPI

app = FastAPI()

# 전역 백그라운드 루프를 안전한 취소 가드 없이 임의 기동
@app.on_event("startup") # 구식 이벤트 핸들러
async def old_startup():
    asyncio.create_task(run_forever_daemon()) # shutdown 시 안전하게 cancel되지 않음

@app.get("/items/{item_id}")
async def get_item(item_id: str):
    from app.database import MyHeavyDatabase # 함수 내 직접 의존성 생성 (테스트 격리 불가)
    db = MyHeavyDatabase()
    return db.query(item_id)
```

---

### ✅ Best Practice (Good)

```python
# app/main.py
# [모범]: FastAPI lifespan 컨텍스트 매니저 기반 클린 수명주기 및 의존성 주입
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. 서버 시작 시 백그라운드 데몬 시작
    daemon_task = asyncio.create_task(run_idle_watcher(timeout_sec=900.0))
    yield
    # 2. 서버 종료 시 Graceful Shutdown 보장
    daemon_task.cancel()
    try:
        await daemon_task
    except asyncio.CancelledError:
        pass

app = FastAPI(lifespan=lifespan)

# app/api/deps.py
# [모범]: 재사용 가능한 의존성 주입 프로바이더
def get_db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# app/api/endpoints.py
# [모범]: Depends 주입을 통한 느슨한 결합 및 단위 테스트 용이성
@app.get("/items/{item_id}")
def get_item(item_id: str, db: Session = Depends(get_db_session)):
    return item_service.get(db, item_id)
```
