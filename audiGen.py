import asyncio
import edge_tts

TEXT = "Danger! Danger! High Radiactive Zone!"
# Male voice
VOICE_MALE = "en-US-GuyNeural"

# Female voice
VOICE_FEMALE = "en-US-JennyNeural"

async def generate():

    communicate = edge_tts.Communicate(TEXT, VOICE_FEMALE)
    await communicate.save("RadioDanger.mp3")

asyncio.run(generate())