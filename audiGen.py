import asyncio
import edge_tts

TEXT = "Take Off in processing! Pull Up! Pull Up!"
# Male voice
VOICE_MALE = "en-US-GuyNeural"

# Female voice
VOICE_FEMALE = "en-US-JennyNeural"

async def generate():

    communicate = edge_tts.Communicate(TEXT, VOICE_FEMALE)
    await communicate.save("TakeOff.mp3")

asyncio.run(generate())