
import gc
import uos as os
import uasyncio as asyncio
import task_mqtt                  # The MQTT task keeps us connected to the LAN


## Directory from which files can be downloaded
ROOT_DIR = "/sd"
HOST = "0.0.0.0"
PORT = 80                # change to 8080 etc. if 80 is in use


# Map an HTTP URL path (e.g. "/", "/foo/bar.txt") to a filesystem path
# under ROOT_DIR, with basic sanitizing.
def map_url_to_path(url_path):

    # Strip query string, e.g. "/file.txt?x=1" -> "/file.txt"
    if "?" in url_path:
        url_path = url_path.split("?", 1)[0]

    # Normalize; ensure leading slash
    if not url_path.startswith("/"):
        url_path = "/" + url_path

    # Remove duplicate slashes
    while "//" in url_path:
        url_path = url_path.replace("//", "/")

    # Split into components and remove "." and empty parts
    parts = [p for p in url_path.split("/") if p not in ("", ".")]

    # Forbid ".." to stop directory traversal
    for p in parts:
        if p == "..":
            return None

    # ROOT URL ("/") → ROOT_DIR
    if not parts:
        return ROOT_DIR

    # Join ROOT_DIR with the sanitized subpath
    fs_path = ROOT_DIR + "/" + "/".join(parts)
    return fs_path


async def send_response_header(writer, status="200 OK",
                               content_type="text/plain", extra_headers=None):
    writer.write("HTTP/1.1 {}\r\n".format(status))
    writer.write("Content-Type: {}\r\n".format(content_type))
    if extra_headers:
        for k, v in extra_headers.items():
            writer.write("{}: {}\r\n".format(k, v))
    writer.write("Connection: close\r\n\r\n")
    await writer.drain()


async def send_404(writer):
    await send_response_header(writer, "404 Not Found", "text/plain")
    writer.write("404 Not Found\r\n")
    await writer.drain()


async def send_400(writer):
    await send_response_header(writer, "400 Bad Request", "text/plain")
    writer.write("400 Bad Request\r\n")
    await writer.drain()


async def handle_directory_listing(writer, dir_path, url_path):
    try:
        entries = os.listdir(dir_path)
    except OSError:
        await send_404(writer)
        return

    await send_response_header(writer, "200 OK", "text/html")

    writer.write("<html><body>\n")
    writer.write("<h1>Bogan Radar SD Card</h1>\n<ul>\n")

    for name in entries:
        if url_path in ("", "/"):
            href = "/" + name
        elif url_path.endswith("/"):
            href = url_path + name
        else:
            href = url_path + "/" + name

        writer.write(f'<li><a href="{href}">{name}</a></li>\n')

    writer.write("</ul>\n</body></html>\n")
    await writer.drain()


async def send_file(writer, full_path):
    try:
        st = os.stat(full_path)
        size = st[6]
    except OSError:
        await send_404(writer)
        return

    # Very basic MIME type guess
    if full_path.endswith(".html") or full_path.endswith(".htm"):
        ctype = "text/html"
    elif full_path.endswith(".txt"):
        ctype = "text/plain"
    elif full_path.endswith(".csv") or full_path.endswith(".sacsv"):
        ctype = "text/csv"
    else:
        ctype = "application/octet-stream"

    headers = {
        "Content-Length": str(size),
        "Content-Disposition": 'attachment; filename="{}"'.format(
            full_path.split("/")[-1]
        ),
    }
    await send_response_header(writer, "200 OK", ctype, headers)

    try:
        f = open(full_path, "rb")
    except OSError:
        await send_404(writer)
        return

    try:
        while True:
            chunk = f.read(1024)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
    finally:
        f.close()


async def handle_client(reader, writer):
    try:
        # --- Request line ---
        line = await reader.readline()
        if not line:
            await writer.aclose()
            return

        request_line = line.decode().strip()
        parts = request_line.split()
        if len(parts) != 3:
            await send_400(writer)
            await writer.aclose()
            return

        method, url_path, _ = parts

        # DEBUG: show what we got
        print("Request:", method, url_path)

        if method != "GET":
            await send_response_header(
                writer, "405 Method Not Allowed", "text/plain", {"Allow": "GET"}
            )
            writer.write("405 Method Not Allowed\r\n")
            await writer.drain()
            await writer.aclose()
            return

        # --- Skip headers ---
        while True:
            hline = await reader.readline()
            if not hline:
                break
            if hline == b"\r\n" or hline == b"\n":
                break

        # --- Map URL to filesystem path ---
        full_path = map_url_to_path(url_path)
        print("Mapped URL '{}' -> '{}'".format(url_path, full_path))

        if not full_path:
            await send_400(writer)
            await writer.aclose()
            return

        # --- Check whether path exists and is file or dir ---
        try:
            st = os.stat(full_path)
        except OSError:
            print("stat() failed:", full_path)
            await send_404(writer)
            await writer.aclose()
            return

        mode = st[0]
        is_dir = (mode & 0x4000) != 0  # directory bit on most MicroPython ports

        if is_dir:
            await handle_directory_listing(writer, full_path, url_path)
        else:
            await send_file(writer, full_path)

    except Exception as e:
        print("Error in handle_client:", e)
    finally:
        try:
            await writer.aclose()
        except Exception:
            pass


async def file_server_task():
    server = await asyncio.start_server(handle_client, HOST, PORT, backlog=1)
#     print(f"Web server: {server}")
    # Small delay before MQTT so Wi-Fi and TCP settle
    await asyncio.sleep_ms(2_000)
    gc.collect()
#     task_mqtt.web_start_done = True
    print("Memory after file server start:", gc.mem_free())
#     addr = server.sockets[0].getsockname()
#     print("HTTP file server listening on {}:{}".format(addr[0], addr[1]))
    await server.wait_closed()


if __name__ == "__main__":

    # Example of another task using the LAN at the same time
    async def other_lan_task():
        while True:
            # e.g. poll some TCP socket, send data to broker, etc.
            print("Other LAN task doing work...")
            await asyncio.sleep(5)


    async def main():
        # Assume network interface (LAN/WLAN) is already up and has an IP address

        # Make sure /sd exists and is mounted
        print("Root entries:", os.listdir("/"))

        # Start file server
        asyncio.create_task(file_server_task())

        # Start your other LAN-using tasks
        asyncio.create_task(other_lan_task())

        # Keep the event loop alive
        while True:
            await asyncio.sleep(3600)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Ctrl-C. Exit.")

