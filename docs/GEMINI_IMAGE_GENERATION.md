# Gemini image generation

Saumya AI's composer mode menu now includes **Create image**. It uses Google's
Gemini image-generation API (Nano Banana 2), not the Gemini website UI session.

1. Create an API key in [Google AI Studio](https://aistudio.google.com/apikey).
2. On the VM, add the key to `~/aichatbot/.env` without committing it:

   ```env
   GEMINI_API_KEY=your_key
   GEMINI_IMAGE_MODEL=gemini-3.1-flash-image
   IMAGE_OUTPUT_DIR=data/generated_images
   ```

3. Pull and rebuild the app:

   ```bash
   cd ~/aichatbot
   git pull
   docker compose up --build -d
   ```

4. In Saumya AI, choose **Images** from the composer mode menu, enter a prompt,
   and send. Generated PNGs are saved in `data/generated_images` (persisted by
   the Compose `./data:/app/data` volume), with an in-chat preview/download link.

The API has separate model/project quotas and billing from the Gemini consumer
app or Google AI plan. Check the Google AI Studio/API project usage and pricing
before regular use; image output contains a SynthID watermark per Google's API
documentation.