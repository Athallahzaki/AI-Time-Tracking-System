import logging
import threading
import queue
import argparse

from engine.app.main import build_app

logger = logging.getLogger(__name__)


class EngineService:

    def __init__(self, source: str):
        self.source = source

        self.engine = None
        self.thread = None
        self.running = False

        self.clients = []
        self.lock = threading.Lock()

        self.last_data = None

    def start(self):

        if self.running:
            return

        self.running = True

        self.thread = threading.Thread(
            target=self._run,
            daemon=True
        )

        self.thread.start()

    def _run(self):

        logger.info("======================================")
        logger.info("STARTING AI VISION ENGINE")
        logger.info("======================================")
        logger.info("Source: %s", self.source)

        args = argparse.Namespace(
            config="engine/configs/default_config.yaml",
            source=self.source,
            device=None,
            mock=False,
            no_face_recognition=True,
            headless=True,
            max_frames=None,
        )

        try:

            # ==================================
            # BUILD ENGINE
            # ==================================

            self.engine = build_app(args)

            logger.info("Engine built successfully.")

            # ==================================
            # START ENGINE
            # ==================================

            self.engine.start()

            logger.info("Engine started successfully.")

            # ==================================
            # PROCESS LOOP
            # ==================================

            while self.running and self.engine.is_running:

                frame, tracks = self.engine.step()

                # Stream ended or video file finished
                if frame is None:
                    logger.info("Frame source exhausted or stream ended.")
                    break

                # ==================================
                # FRAME INFO
                # ==================================

                width = frame.width
                height = frame.height

                # ==================================
                # TRACK DATA
                # ==================================

                people = []

                for track in tracks:

                    attrs = getattr(track, "attributes", {}) or {}
                    presence_status = attrs.get("presence_status", "PASSING")
                    identity = attrs.get("identity")
                    similarity = float(attrs.get("similarity", 0.0))
                    session_elapsed = float(attrs.get("session_elapsed", track.dwell_time))

                    people.append({
                        "track_id": int(track.track_id),

                        "bbox": {
                            "x1": float(track.bbox.x1),
                            "y1": float(track.bbox.y1),
                            "x2": float(track.bbox.x2),
                            "y2": float(track.bbox.y2),
                        },

                        "confidence": float(
                            track.confidence
                        ),

                        "state": track.state.value,

                        "dwell_time": float(
                            track.dwell_time
                        ),

                        "presence_status": presence_status,
                        "identity": identity,
                        "similarity": similarity,
                        "session_elapsed": session_elapsed,
                    })

                # ==================================
                # FPS ENGINE
                # ==================================

                fps = self.engine.metrics.fps

                # ==================================
                # DATA SSE
                # ==================================

                data = {
                    "camera_id": "cam-01",

                    "frame_id": frame.frame_id,

                    "width": width,
                    "height": height,

                    "fps": round(fps, 2),

                    "people": people,
                }

                self.last_data = data

                # ==================================
                # SEND TO SSE CLIENTS
                # ==================================

                with self.lock:

                    for client_queue in self.clients:

                        try:
                            client_queue.put_nowait(data)

                        except queue.Full:
                            # Drop the oldest frame and push the latest
                            try:
                                client_queue.get_nowait()
                            except queue.Empty:
                                pass

                            try:
                                client_queue.put_nowait(data)
                            except queue.Full:
                                pass

        except Exception as e:
            logger.exception("Engine encountered a fatal error: %s: %s", type(e).__name__, e)

        finally:

            if self.engine is not None:

                try:
                    self.engine.stop()
                except Exception:
                    pass

            self.running = False

            logger.info("Engine stopped.")

    def subscribe(self):

        client_queue = queue.Queue(maxsize=2)

        with self.lock:
            self.clients.append(client_queue)

        return client_queue

    def unsubscribe(self, client_queue):

        with self.lock:

            if client_queue in self.clients:
                self.clients.remove(client_queue)

    def stop(self):

        self.running = False

        if self.engine is not None:
            self.engine.stop()