# Model Usage

This project now uses a single fixed model convention:

- Put your trained YOLO weight file in `models/best.pt`
- Do not change model paths in `.env`
- Do not configure demo mode

## Local Usage

- Keep the weight file at `models/best.pt`
- Start the stack normally
- The worker will always load `models/best.pt`

## Docker Usage

- Build with `docker compose up --build` or `docker compose build worker`
- The `worker` image now packages the `models` directory into `/app/models`
- Local compose also mounts `./models` to `/app/models`, so replacing `models/best.pt` updates the runtime model without changing code

## Expected Behavior

- If `models/best.pt` exists, the worker uses it automatically
- If `models/best.pt` is missing, the worker fails with a clear error telling you to place the model at `models/best.pt`
