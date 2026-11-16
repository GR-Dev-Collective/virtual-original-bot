/**
 * Capture the built Electron renderer as a PNG for UI acceptance.
 *
 * Usage (after `npm run build`):
 *   python -m http.server 4173 --directory out/renderer
 *   npx electron scripts/capture_ui.cjs
 *
 * Environment:
 *   VOB_CAPTURE_URL  default http://127.0.0.1:4173/
 *   VOB_CAPTURE_OUT  default ui-capture.png in the current directory
 */
const { app, BrowserWindow } = require('electron')
const fs = require('node:fs')
const path = require('node:path')

const url = process.env.VOB_CAPTURE_URL || 'http://127.0.0.1:4173/'
const outPath = process.env.VOB_CAPTURE_OUT || path.join(process.cwd(), 'ui-capture.png')

app.commandLine.appendSwitch('disable-gpu-sandbox')

app.whenReady().then(async () => {
  const window = new BrowserWindow({
    width: 1100,
    height: 760,
    show: false,
    backgroundColor: '#0f1116',
    webPreferences: {
      sandbox: false,
      autoplayPolicy: 'no-user-gesture-required'
    }
  })

  await window.loadURL(url)
  await new Promise((resolve) => setTimeout(resolve, 9000))

  const status = await window.webContents.executeJavaScript(
    "({ live2d: document.getElementById('live2d-status')?.textContent || '', connection: document.getElementById('status')?.textContent || '', title: document.title })"
  )
  const image = await window.webContents.capturePage()
  fs.writeFileSync(outPath, image.toPNG())
  console.log(
    JSON.stringify({
      url,
      out: outPath,
      size: image.getSize(),
      status
    })
  )
  app.quit()
})
