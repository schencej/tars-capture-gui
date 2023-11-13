from trame.app import get_server, asynchronous
from trame.ui.vuetify import VAppLayout, SinglePageLayout
from trame.widgets import html, vuetify
from aiohttp import web, ClientSession
from aiohttp.client_exceptions import ClientConnectorError
import socketio
import base64
import asyncio
from threading import Timer

class CaptureGUI:
    def __init__(self):
        self.server = get_server()
        # self.server.client_type = 'vue3'

        self.socket_server = socketio.AsyncServer(async_mode='aiohttp')
        self.socket_server.on('connect')(self.handle_camera_connection)
        self.socket_server.on('ip_addr')(self.handle_camera_ip)
        self.socket_server.on('disconnect')(self.handle_camera_disconnect)
        self.socket_server.on('status')(self.handle_camera_status)
        self.socket_server.on('frame')(self.handle_frame)
        self.sid_to_ip = {}
        self.updating_img_width = False

        state = self.server.state
        state.cams_per_row = 4
        state.num_cams = 8
        state.recording = False
        state.trame__title = "TARS Capture"
        state.selected_server = None
        state.camera_clients = {}

        state.change("selected_server")(self.on_server_select)
        state.change("img_div_width")(self.on_img_div_width)

        self.state = state

        self.server.controller.add("on_server_bind")(self.on_app_available)

    def on_app_available(self, wslink_server):
        self.socket_server.attach(wslink_server.app)

    def handle_camera_connection(self, sid, environ):
        print('connection')
        # print(sid)
        # for k, v in environ.items():
        #     try:
        #         print(f"{k}: {v}")
        #     except:
        #         print(k)

    async def handle_camera_ip(self, sid, ip_addr):
        print(f"Got ip {ip_addr}")
        self.sid_to_ip[sid] = ip_addr
        self.state.camera_clients[ip_addr] = {}
        self.state.dirty('camera_clients')
        self.state.flush()
        await asyncio.sleep(0.1)

    async def handle_camera_disconnect(self, sid):
        print('disconnect')
        ip = self.sid_to_ip[sid]
        del self.state.camera_clients[ip]
        self.state.dirty('camera_clients')
        self.state.flush()
        await asyncio.sleep(0.1)

    async def handle_camera_status(self, sid, status_list):
        # print('camera_status')
        ip = self.sid_to_ip[sid]
        # print(ip)

        info = {
            'num_cams': len(status_list),
            'cams_up': sum(1 for s in status_list if s),
        }

        self.state.camera_clients[ip] = info
        self.state.dirty('camera_clients')
        self.state.flush()
        await asyncio.sleep(0.1)

    def send_next_frame(self, frame_idx):
        selected_server = self.state.selected_server
        if selected_server and not self.updating_img_width:
            asyncio.ensure_future(self.socket_server.emit(f"frame", (selected_server, frame_idx)))

    async def handle_frame(self, sid, idx, frame):
        if not self.updating_img_width:
            self.state[f"frame_{idx}"] = f"data:image/jpeg;base64,{base64.encodebytes(frame).decode('utf-8')}"

    async def on_server_select(self, selected_server, **kwargs):
        if selected_server:
            asyncio.ensure_future(self.socket_server.emit('frames', selected_server))
        else:
            for i in range(8):
                self.state[f"frame_{i}"] = None

    def start_img_width_update(self):
        self.updating_img_width = True

    def stop_img_width_update(self):
        self.updating_img_width = False
        asyncio.ensure_future(self.socket_server.emit('frames', self.state.selected_server))

    async def on_img_div_width(self, img_div_width, **kwargs):
        with self.state as state:
            state.img_div_style = (
                "border: solid gray 2px;"
                "border-radius: 15px;"
                "margin: 5px;"
                "padding: 5px;"
                "max-width: 100%;"
                f"width: {img_div_width}%;"
            )
        await asyncio.sleep(0.1)

    async def record_all(self):
        self.state.recording = True
        asyncio.ensure_future(self.socket_server.emit('start_capture', 'all'))

    def stop_all(self):
        # TODO: add this
        self.state.recording = False
        asyncio.ensure_future(self.socket_server.emit('stop_capture', 'all'))

    def get_ui(self):
        with SinglePageLayout(self.server) as main_page:
            main_page.title.set_text("TARS Capture")

            with main_page.toolbar:
                with html.Div(
                    style=(
                        "position: absolute;"
                        "height: 100%;"
                        "width: 100%;"
                        "display: flex;"
                        "justify-content: center;"
                        "align-items: center;"
                    )
                ):
                    with vuetify.VBtn(
                        "Capture",
                        v_if="selected_server == undefined && !recording",
                        loading=("waiting_for_record_start", False),
                        click=self.record_all,
                    ):
                        vuetify.VIcon("mdi-record-rec")

                    with vuetify.VBtn(
                        "Stop",
                        v_if=("selected_server == undefined && recording",),
                        click=self.stop_all,
                    ):
                        vuetify.VIcon("mdi-stop-circle-outline")

                    with vuetify.VBtn(
                        v_if="selected_server != undefined",
                        icon=True,
                        click="selected_server = undefined",
                    ):
                        vuetify.VIcon("mdi-home")

                vuetify.VSpacer()
                with html.Div(
                    v_show="selected_server != undefined",
                    style=(
                        "display: flex;"
                        "width: 20%;"
                    )
                ):
                    vuetify.VSlider(
                        v_model=("img_div_width", 24),
                        min=10,
                        max=100,
                        start=self.start_img_width_update,
                        end=self.stop_img_width_update,
                        label="Image Width",
                        dense=True,
                    )
                    html.P("{{img_div_width}}%")

            with main_page.content:
                ###################### Camera servers view #####################
                with vuetify.VContainer(
                    v_if="selected_server == undefined",
                    style=(
                        "display: flex;"
                        "flex-wrap: wrap;"
                    ),
                ):
                    with vuetify.VHover(
                        v_for="client_info, client_ip in camera_clients",
                        v_slot="{ hover }"
                    ):
                        with vuetify.VCard(
                            color=("hover ? 'rgb(240, 240, 240)' : 'white'",),
                            ripple=True,
                            click="selected_server = client_ip",
                            style=(
                                "margin: 10px;"
                            ),
                        ):
                            vuetify.VCardTitle("{{ client_ip }}")
                            with vuetify.VCardText():
                                vuetify.VIcon(
                                    'mdi-camera-outline',
                                    v_for=("n in client_info['num_cams']",),
                                    color=("n <= client_info['cams_up'] ? 'green' : 'red'",),
                                )

                ######################## Cam feed view #########################
                with vuetify.VContainer(
                    v_if="selected_server != undefined",
                    fluid=True,
                    style=(
                        "display: flex;"
                        "flex-wrap: wrap;"
                        "justify-content: center;"
                    ),
                ):
                    for n in range(8):
                        with vuetify.VContainer(
                            v_if=f"{n} < num_cams",
                            style=(
                                "img_div_style",
                                (
                                    "border: solid gray 2px;"
                                    "border-radius: 15px;"
                                    "margin: 5px;"
                                    "padding: 5px;"
                                    "max-width: 100%;"
                                    "width: 24%;"
                                )
                            ),
                        ):
                            vuetify.VImg(
                                src=(f"frame_{n}", ""),
                                load=(self.send_next_frame, f"[{n}]"),
                                lazy_src="https://media.licdn.com/dms/image/D4D0BAQGceM14Ipkgyg/company-logo_200_200/0/1684474861204?e=2147483647&v=beta&t=utuM6ulkiVg361TUBI9Yh15EyjRIAjgQb18VM1QWqyQ",
                                aspect_ratio=1,
                            )

    def get_server(self):
        return self.server

if __name__ == '__main__':
    capture_gui = CaptureGUI()

    server = capture_gui.get_server()
    capture_gui.get_ui()

    server.start()
