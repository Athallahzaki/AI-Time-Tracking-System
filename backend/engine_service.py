import threading
import time
import queue
import argparse

from engine.app.main import build_app


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

        print()
        print("======================================")
        print("STARTING AI VISION ENGINE")
        print("======================================")
        print("Source:", self.source)
        print()

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

            print("Engine berhasil dibuat.")

            # ==================================
            # START ENGINE
            # ==================================

            self.engine.start()

            print("Engine berhasil START.")
            print()

            # ==================================
            # PROCESS LOOP
            # ==================================

            while self.running and self.engine.is_running:

                frame, tracks = self.engine.step()

                # Video selesai
                if frame is None:

                    print("Frame kosong / video selesai.")

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

                    bbox = track.bbox

                    people.append({
                        "track_id": int(track.track_id),

                        "bbox": {
                            "x1": float(bbox.x1),
                            "y1": float(bbox.y1),
                            "x2": float(bbox.x2),
                            "y2": float(bbox.y2),
                        },

                        "confidence": float(
                            track.confidence
                        ),

                        "state": track.state.value,

                        "dwell_time": float(
                            track.dwell_time
                        ),
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

                            # Buang data lama
                            try:
                                client_queue.get_nowait()
                            except queue.Empty:
                                pass

                            try:
                                client_queue.put_nowait(data)
                            except queue.Full:
                                pass

        except Exception as e:

            print()
            print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
            print("ENGINE ERROR")
            print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
            print(type(e).__name__)
            print(e)
            print()

        finally:

            if self.engine is not None:

                try:
                    self.engine.stop()
                except Exception:
                    pass

            self.running = False

            print("Engine stopped.")

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