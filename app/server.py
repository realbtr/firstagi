# ── Единственный экземпляр приложения ─────────────────────────────────
@app.route("/learn", methods=["POST"])
def learn():
    # Здесь будет реализовано обучение системы
    return JSONResponse({"message": "Successfully learned."})

# ── FastAPI ────────────────────────────────────────────────────────────
api = FastAPI(
    title="FirstAGI API",
    description="HTTP интерфейс к ядру FirstAGI (прямое исчисление аттрактора).",
    version="0.6.0",
)

# ── Модели запросов ────────────────────────────────────────────────────
class LearnRequest(BaseModel):
    text: str
    driver_id: str = "text"
    reset_after: bool = True

class TeacherOrderRequest(BaseModel):
    required_gens: list[str]
    reward: float = 30.0
