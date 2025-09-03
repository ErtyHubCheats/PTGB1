import numpy as np
from PIL import Image, ImageSequence
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
import cv2, io, tempfile, os
from rlottie_python import LottieAnimation  # <- новый импорт для TGS

TOKEN = "7970689984:AAEovaKrRUn1PzbbwNy-YY7GfZjQCQEU9X4"

# --- обработчики ---
async def handle_media(update: Update, frames: list[np.ndarray]):
    user = update.effective_user
    print(f"[MEDIA] от {user.username or user.id}, кадров: {len(frames)}")
    for i, frame in enumerate(frames[:5]):
        print(f"Кадр {i}: {frame.shape if frame is not None else 'None'}")
    
    if frames:
        success, buffer = cv2.imencode('.jpg', frames[0])
        if success:
            await update.message.reply_photo(
                photo=buffer.tobytes(),
                caption=f"Обработано {len(frames)} кадров\nРазмер: {frames[0].shape[1]}x{frames[0].shape[0]}"
            )
        else:
            await update.message.reply_text(f"Обработано {len(frames)} кадров, но не удалось отправить результат")

def gif_to_frames(file_bytes: bytes) -> list[np.ndarray]:
    """Попробовать распарсить как GIF"""
    frames = []
    try:
        with Image.open(io.BytesIO(file_bytes)) as im:
            for frame in ImageSequence.Iterator(im):
                frame = frame.convert("RGB")
                arr = np.array(frame)
                arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
                frames.append(arr)
    except Exception as e:
        print("gif_to_frames ошибка:", e)
    return frames

def video_to_frames(file_bytes: bytes, ext: str = ".mp4") -> list[np.ndarray]:
    frames = []
    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(file_bytes)
            tmp.flush()
            
            cap = cv2.VideoCapture(tmp.name)
            if not cap.isOpened():
                print("Ошибка открытия видеофайла")
                return frames
                
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                frames.append(frame)
            cap.release()
            
        os.unlink(tmp.name)
    except Exception as e:
        print("video_to_frames ошибка:", e)
    return frames

def tgs_to_frames_rlottie(file_bytes: bytes, scale: int = 2) -> list[np.ndarray]:
    """Конвертация TGS через rlottie-python"""
    frames = []
    try:
        with tempfile.NamedTemporaryFile(suffix='.tgs', delete=False) as tmp:
            tmp.write(file_bytes)
            tmp.flush()
            tmp_path = tmp.name

        # Загружаем анимацию через rlottie
        animation = LottieAnimation.from_tgs(tmp_path)

        total_frames = animation.lottie_animation_get_totalframe()
        width, height = int(animation.lottie_animation_get_size()[0] * scale), int(animation.lottie_animation_get_size()[1] * scale)

        frames = []

        for i in range(total_frames):
            # Получаем raw байты RGBA
            raw = animation.lottie_animation_render(frame_num=i, width=width, height=height)
            
            # Преобразуем bytes в numpy array
            arr = np.frombuffer(raw, dtype=np.uint8).reshape((height, width, 4))  # 4 канала: RGBA
            
            # Конвертируем RGBA в BGR для OpenCV
            img = cv2.cvtColor(arr, cv2.COLOR_RGBA2RGB)
            
            frames.append(img)

        os.unlink(tmp_path)
    except Exception as e:
        print("tgs_to_frames_rlottie ошибка:", e)
    return frames

def webp_to_frames(file_bytes: bytes) -> list[np.ndarray]:
    frames = []
    try:
        from PIL import Image, ImageSequence
        with Image.open(io.BytesIO(file_bytes)) as im:
            if getattr(im, 'is_animated', False):
                for frame in ImageSequence.Iterator(im):
                    frame = frame.convert("RGB")
                    arr = np.array(frame)
                    arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
                    frames.append(arr)
            else:
                img = im.convert("RGB")
                arr = np.array(img)
                arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
                frames.append(arr)
    except Exception as e:
        print("webp_to_frames ошибка:", e)
    return frames

# --- обработка сообщений ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
        
    msg = update.message
    frames = []

    try:
        if msg.photo:
            file = await msg.photo[-1].get_file()
            file_bytes = await file.download_as_bytearray()
            img = cv2.imdecode(np.frombuffer(file_bytes, np.uint8), cv2.IMREAD_COLOR)
            if img is not None:
                frames = [img]

        elif msg.document:
            file = await msg.document.get_file()
            file_bytes = await file.download_as_bytearray()
            ext = os.path.splitext(msg.document.file_name or "")[1].lower()

            if msg.document.mime_type == "image/gif" or ext == ".gif":
                frames = gif_to_frames(file_bytes)
                if not frames:
                    frames = video_to_frames(file_bytes, ".mp4")
            elif ext == ".webp":
                frames = webp_to_frames(file_bytes)
            else:
                img = cv2.imdecode(np.frombuffer(file_bytes, np.uint8), cv2.IMREAD_COLOR)
                if img is not None:
                    frames = [img]

        elif msg.video:
            file = await msg.video.get_file()
            file_bytes = await file.download_as_bytearray()
            frames = video_to_frames(file_bytes, ".mp4")

        elif msg.animation:
            file = await msg.animation.get_file()
            file_bytes = await file.download_as_bytearray()
            frames = video_to_frames(file_bytes, ".mp4")

        elif msg.sticker:
            file = await msg.sticker.get_file()
            file_bytes = await file.download_as_bytearray()
            if msg.sticker.is_animated:
                frames = tgs_to_frames_rlottie(file_bytes)
            elif msg.sticker.is_video:
                frames = video_to_frames(file_bytes, ".webm")
            else:
                frames = webp_to_frames(file_bytes)

        if frames:
            await handle_media(update, frames)
        else:
            await msg.reply_text("Не удалось обработать медиафайл")

    except Exception as e:
        print(f"Ошибка обработки сообщения: {e}")
        import traceback
        traceback.print_exc()
        await msg.reply_text("Произошла ошибка при обработке файла")

# --- команды ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Отправь мне:\n"
        "📷 - Фото\n"
        "🎞️ - GIF\n"
        "📹 - Видео\n"
        "🤖 - Стикер (включая анимированные)\n\n"
        "Я покажу информацию о медиафайле и отправлю первый кадр."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Доступные команды:\n"
        "/start - начать работу\n"
        "/help - справка\n\n"
        "Просто отправь мне любой медиафайл для анализа!"
    )

# --- запуск бота ---
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))
    print("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
