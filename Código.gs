/**
 * BRIDGE AUTH SERVICE v8 — Google Apps Script
 *
 * Reglas de sesión:
 *   - El token SOLO se invalida con: logout explícito, cierre de app (cliente llama logout),
 *     o login con force_new_session (tomar sesión en este equipo).
 *   - Heartbeat NO expira la sesión por tiempo; solo confirma token y actualiza LAST_HEARTBEAT.
 *     Si cambia la IP pública durante la sesión, se actualiza SESSION_IP (roaming) sin bloquear.
 *   - Bloqueo 24 h (BLOCKED_UNTIL): solo por muchos intentos fallidos de contraseña del MISMO usuario.
 *   - Si hay sesión activa y el mismo usuario entra desde otra WAN: NO bloqueo 24 h.
 *     Se responde code=session_active_other_network; el cliente puede reintentar con force_new_session.
 *   - Columnas extra: SESSION_STARTED, LAST_HEARTBEAT (última fila de usuarios).
 *
 * Ejecutar resetearHojas() si faltan columnas.
 */

const APP_SECRET        = "AiRc0n3ktA_S3cr3t_2025!";
const SHEET_USUARIOS    = "usuarios";
const SHEET_LOGIN       = "logs_login";
const SHEET_SSH         = "logs_ssh";
const SHEET_SOLICITUDES = "solicitudes";
const SHEET_CONFIGS     = "configs_usuarios";
/** Hoja opcional: semilla por usuario para cifrado Bridge (no toca usuarios/configs). */
const SHEET_BRIDGE_SEM  = "bridge_semillas";

const HDR_BRIDGE_SEM = [
  "USUARIO",
  "SEMILLA_BRIDGE"
];

/** Índices 0-based en fila de datos (fila 1 = headers) */
const COL = {
  USUARIO: 0, CLAVE_HASH: 1, ACTIVO: 2, INTENTOS_FALLIDOS: 3, INTENTOS_EXITOSOS: 4,
  ULTIMO_ACCESO: 5, EMPRESA: 6, CORREO: 7, NOTAS: 8,
  SESSION_TOKEN: 9, SESSION_IP: 10, BLOCKED_UNTIL: 11,
  SESSION_STARTED: 12, LAST_HEARTBEAT: 13
};

const HDR_USUARIOS = [
  "USUARIO","CLAVE_HASH","ACTIVO","INTENTOS_FALLIDOS",
  "INTENTOS_EXITOSOS","ULTIMO_ACCESO","EMPRESA","CORREO","NOTAS",
  "SESSION_TOKEN","SESSION_IP","BLOCKED_UNTIL",
  "SESSION_STARTED","LAST_HEARTBEAT"
];

const HDR_LOGIN = [
  "FECHA","ESTADO","USUARIO APP","EMPRESA",
  "IP PUBLICA","IP LAN","USUARIO WINDOWS","NOMBRE PC",
  "SISTEMA OPERATIVO","ES ADMIN","VERSION","DETALLE"
];

const HDR_SSH = [
  "FECHA CONEXION","FECHA DESCONEXION","DURACION","ESTADO",
  "USUARIO APP","EMPRESA",
  "IP PUBLICA","IP LAN","USUARIO WINDOWS","NOMBRE PC",
  "SISTEMA OPERATIVO","ES ADMIN",
  "IP SSH","USUARIO SSH","CLAVE SSH",
  "IP INTERNA","REDES LAN",
  "URL CLIENTES","SSH USER DEFAULT","VERSION"
];

const HDR_SOLICITUDES = [
  "FECHA","USUARIO","CORREO","EMPRESA",
  "TELEFONO","WHATSAPP","IP ORIGEN","VERSION",
  "ESTADO","FECHA REVISION","NOTAS ADMIN"
];

const HDR_CONFIGS = [
  "TIMESTAMP","USUARIO","EMPRESA","SSH_USER","SSH_PASS",
  "SHEETS_URL","PC_NOMBRE","IP_PUBLICA","VERSION","ETIQUETA"
];

const BLOQUEO_MS           = 24 * 60 * 60 * 1000;
const MAX_FALLOS_CLAVE     = 5;
const WAN_COOLDOWN_MS      = 60 * 60 * 1000;

function doPost(e) {
  try {
    const body = JSON.parse(e.postData.contents);
    if (body.app_secret !== APP_SECRET)
      return _resp({ok:false, msg:"no_auth"});
    const action = body.action || "login";
    if (action === "login")            return _handleLogin(body);
    if (action === "registro")         return _handleRegistro(body);
    if (action === "ssh_open")         return _handleSshOpen(body);
    if (action === "ssh_close")        return _handleSshClose(body);
    if (action === "guardar_config")   return _handleGuardarConfig(body);
    if (action === "cargar_configs")   return _handleCargarConfigs(body);
    if (action === "etiquetar_config") return _handleEtiquetarConfig(body);
    if (action === "heartbeat")        return _handleHeartbeat(body);
    if (action === "logout")           return _handleLogout(body);
    return _resp({ok:false, msg:"unknown_action"});
  } catch(err) {
    return _resp({ok:false, msg:"server_error", detail:err.toString()});
  }
}

function doGet(e) {
  return ContentService.createTextOutput(
    JSON.stringify({status:"ok", service:"bridge-auth-v8"})
  ).setMimeType(ContentService.MimeType.JSON);
}

function _rowGet(row, colIdx) {
  return String(row[colIdx] != null ? row[colIdx] : "").trim();
}

/**
 * Semilla por operador (columna SEMILLA_BRIDGE) para combinar con bridge.key en el cliente.
 * Si la hoja no existe o la fila está vacía, devuelve "" (el cliente usa solo cifrado local NSC1).
 */
function _getBridgeSemilla(ss, usuario) {
  const u = (usuario || "").trim().toLowerCase();
  if (!u) return "";
  const sheet = ss.getSheetByName(SHEET_BRIDGE_SEM);
  if (!sheet) return "";
  const data = sheet.getDataRange().getValues();
  for (let i = 1; i < data.length; i++) {
    const row = data[i];
    const rowUser = _rowGet(row, 0);
    if (rowUser.toLowerCase() !== u) continue;
    return _rowGet(row, 1);
  }
  return "";
}

function _clearSessionCells(sheet, row1Based) {
  sheet.getRange(row1Based, 10).setValue("");
  sheet.getRange(row1Based, 11).setValue("");
  sheet.getRange(row1Based, 13).setValue("");
  sheet.getRange(row1Based, 14).setValue("");
}

function _handleLogin(body) {
  const usuario = (body.usuario || "").trim().toLowerCase();
  const clave   = (body.clave   || "").trim();
  const version = (body.version || "?");
  const ip      = (body.ip_publica || body.ip || "").trim() || "?";
  const forceNew = body.force_new_session === true || body.force_new_session === "true";

  if (!usuario || !clave) {
    _logLogin("FALLIDO", usuario, body, version, "Campos vacíos");
    return _resp({ok:false, msg:"empty_fields", code:"empty_fields"});
  }

  const ss    = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = _hoja(ss, SHEET_USUARIOS, HDR_USUARIOS);
  const data  = sheet.getDataRange().getValues();

  for (let i = 1; i < data.length; i++) {
    const row = data[i];
    const rowUser = _rowGet(row, COL.USUARIO);
    if (!rowUser || rowUser !== usuario) continue;

    let rowFail = parseInt(row[COL.INTENTOS_FALLIDOS]) || 0;
    let rowOk   = parseInt(row[COL.INTENTOS_EXITOSOS]) || 0;
    const rowHash = _rowGet(row, COL.CLAVE_HASH);
    const rowActivo = _rowGet(row, COL.ACTIVO).toUpperCase();
    let rowSessToken = _rowGet(row, COL.SESSION_TOKEN);
    const rowSessIP  = _rowGet(row, COL.SESSION_IP);
    let rowBlockedUntil = _rowGet(row, COL.BLOCKED_UNTIL);
    const rowSessionStarted = _rowGet(row, COL.SESSION_STARTED);

    if (rowBlockedUntil) {
      const until = new Date(rowBlockedUntil).getTime();
      if (Date.now() < until) {
        const resta = Math.ceil((until - Date.now()) / 3600000);
        _logLogin("BLOQUEADO", usuario, body, version, "Bloqueo por intentos fallidos");
        return _resp({
          ok:false,
          code:"account_locked",
          msg:`Demasiados intentos fallidos. Espera ${resta} hora(s) o contacta al administrador.`
        });
      }
      sheet.getRange(i + 1, 12).setValue("");
      rowBlockedUntil = "";
    }

    if (rowActivo !== "SI") {
      rowFail++;
      _updateCounters(sheet, i + 1, rowFail, rowOk, null);
      _logLogin("BLOQUEADO", usuario, body, version, "Usuario desactivado");
      return _resp({ok:false, msg:"user_disabled", code:"user_disabled"});
    }

    if (clave !== rowHash) {
      rowFail++;
      _updateCounters(sheet, i + 1, rowFail, rowOk, null);
      _logLogin("FALLIDO", usuario, body, version, "Clave incorrecta");
      if (rowFail >= MAX_FALLOS_CLAVE) {
        const blockedUntil = new Date(Date.now() + BLOQUEO_MS).toISOString();
        sheet.getRange(i + 1, 12).setValue(blockedUntil);
        sheet.getRange(i + 1, 4).setValue(0);
        _logLogin("BLOQUEADO", usuario, body, version, "Bloqueo 24h por intentos fallidos");
        return _resp({
          ok:false,
          code:"account_locked",
          msg:"Demasiados intentos fallidos. Cuenta bloqueada 24 horas."
        });
      }
      return _resp({ok:false, msg:"wrong_password", code:"wrong_password"});
    }

    if (rowSessToken === "KICKED") {
      _clearSessionCells(sheet, i + 1);
      rowSessToken = "";
    }

    if (rowSessToken && !forceNew) {
      if (rowSessIP && rowSessIP !== ip) {
        let withinCooldown = false;
        if (rowSessionStarted) {
          const t0 = new Date(rowSessionStarted).getTime();
          if (!isNaN(t0) && (Date.now() - t0) < WAN_COOLDOWN_MS)
            withinCooldown = true;
        }
        _logLogin("SESION_OTRA_RED", usuario, body, version,
          "Activa otra sesión IP=" + rowSessIP + " nuevo=" + ip);
        return _resp({
          ok:false,
          code:"session_active_other_network",
          msg:"Ya hay una sesión abierta con este usuario desde otra red (otra IP). " +
              "Puedes «Tomar sesión» en este equipo, cerrar la app en el otro, o esperar 1 hora.",
          session_from_ip: rowSessIP,
          within_cooldown: withinCooldown
        });
      }
    }

    if (rowSessToken && forceNew) {
      _clearSessionCells(sheet, i + 1);
      _logLogin("TAKEOVER", usuario, body, version, "force_new_session desde " + ip);
    }

    const token = _genToken();
    const nowIso = new Date().toISOString();
    sheet.getRange(i + 1, 10).setValue(token);
    sheet.getRange(i + 1, 11).setValue(ip);
    sheet.getRange(i + 1, 12).setValue("");
    sheet.getRange(i + 1, 13).setValue(nowIso);
    sheet.getRange(i + 1, 14).setValue(nowIso);
    sheet.getRange(i + 1, 4).setValue(0);

    rowOk++;
    _updateCounters(sheet, i + 1, 0, rowOk, _ts());
    _logLogin("EXITOSO", usuario, body, version, "Acceso correcto");

    const cfgBody = _handleCargarConfigs({usuario: usuario});
    const cfgData = JSON.parse(cfgBody.getContent());
    const latest  = cfgData.configs && cfgData.configs.length > 0 ? cfgData.configs[0] : null;
    const bridgeSemilla = _getBridgeSemilla(ss, usuario);
    return _resp({
      ok: true,
      msg: "ok",
      usuario: usuario,
      session_token: token,
      config: latest,
      bridge_semilla: bridgeSemilla
    });
  }

  _logLogin("FALLIDO", usuario, body, version, "Usuario no existe");
  return _resp({ok:false, msg:"user_not_found", code:"user_not_found"});
}

function _handleHeartbeat(body) {
  const usuario = (body.usuario || "").trim().toLowerCase();
  const token   = (body.session_token || "").trim();
  const ip      = (body.ip_publica || body.ip || "").trim() || "?";

  if (!usuario || !token)
    return _resp({ok:false, kicked:true, motivo:"Datos de sesión inválidos."});

  const ss    = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = _hoja(ss, SHEET_USUARIOS, HDR_USUARIOS);
  const data  = sheet.getDataRange().getValues();

  for (let i = 1; i < data.length; i++) {
    const row = data[i];
    const rowUser = _rowGet(row, COL.USUARIO);
    if (rowUser !== usuario) continue;

    const rowToken  = _rowGet(row, COL.SESSION_TOKEN);
    const rowBlocked= _rowGet(row, COL.BLOCKED_UNTIL);

    if (rowBlocked) {
      const until = new Date(rowBlocked).getTime();
      if (Date.now() < until) {
        return _resp({ok:false, kicked:true,
          motivo:"Cuenta bloqueada por intentos fallidos. Contacta al administrador."});
      }
    }

    if (rowToken === "KICKED" || !rowToken) {
      return _resp({ok:false, kicked:true,
        motivo:"La sesión ya no es válida. Vuelve a iniciar sesión."});
    }

    if (rowToken !== token) {
      return _resp({ok:false, kicked:true,
        motivo:"Otro inicio de sesión reemplazó esta sesión."});
    }

    sheet.getRange(i + 1, 14).setValue(new Date().toISOString());
    if (ip && ip !== "?")
      sheet.getRange(i + 1, 11).setValue(ip);

    return _resp({ok:true, kicked:false});
  }

  return _resp({ok:false, kicked:true, motivo:"Usuario no encontrado."});
}

function _handleLogout(body) {
  const usuario = (body.usuario || "").trim().toLowerCase();
  const token   = (body.session_token || "").trim();

  const ss    = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = _hoja(ss, SHEET_USUARIOS, HDR_USUARIOS);
  const data  = sheet.getDataRange().getValues();

  for (let i = 1; i < data.length; i++) {
    const rowUser = _rowGet(data[i], COL.USUARIO);
    if (rowUser !== usuario) continue;
    const rowToken = _rowGet(data[i], COL.SESSION_TOKEN);
    if (!token || rowToken === token || rowToken === "KICKED") {
      _clearSessionCells(sheet, i + 1);
    }
    return _resp({ok:true, msg:"logged_out"});
  }
  return _resp({ok:false, msg:"user_not_found"});
}

function _handleRegistro(body) {
  const usuario   = (body.usuario  || "").trim().toLowerCase();
  const correo    = (body.correo   || "").trim();
  const empresa   = (body.empresa  || "").trim();
  const telefono  = (body.telefono || "").trim();
  const whatsapp  = (body.whatsapp || "").trim();
  const ip        = (body.ip_publica || body.ip || "?");
  const version   = (body.version  || "?");
  const claveHash = (body.clave    || "").trim();

  if (!usuario || !correo || !empresa || !claveHash)
    return _resp({ok:false, msg:"Faltan campos obligatorios"});

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheetU = _hoja(ss, SHEET_USUARIOS, HDR_USUARIOS);
  const dataU  = sheetU.getDataRange().getValues();
  for (let i = 1; i < dataU.length; i++) {
    if (!dataU[i][0]) continue;
    if (String(dataU[i][0]).trim().toLowerCase() === usuario)
      return _resp({ok:false, msg:"El usuario ya existe. Intenta iniciar sesión."});
  }

  const sheetS = _hoja(ss, SHEET_SOLICITUDES, HDR_SOLICITUDES);
  const dataS  = sheetS.getDataRange().getValues();
  for (let i = 1; i < dataS.length; i++) {
    if (!dataS[i][1]) continue;
    if (String(dataS[i][1]).trim().toLowerCase() === usuario &&
        String(dataS[i][8]).trim().toUpperCase().includes("PENDIENTE"))
      return _resp({ok:false, msg:"Ya tienes una solicitud pendiente."});
  }

  const row = [_ts(), usuario, correo, empresa, telefono, whatsapp,
               ip, version, "Pendiente", "", ""];
  sheetS.appendRow(row);
  const lastRow = sheetS.getLastRow();
  sheetS.getRange(lastRow, 12).setValue(claveHash);
  sheetS.getRange(lastRow, 9).setValue("Pendiente");
  sheetS.getRange(lastRow, 1, 1, HDR_SOLICITUDES.length).setBackground("#fff3cd");

  try {
    const owner = Session.getActiveUser().getEmail();
    if (owner) GmailApp.sendEmail(owner,
      "Nueva solicitud — " + empresa,
      "Usuario: "+usuario+"\nEmpresa: "+empresa+"\nCorreo: "+correo+"\nIP: "+ip);
  } catch(e) {}

  return _resp({ok:true, msg:"Solicitud enviada. Espera la aprobación del administrador."});
}

function _handleSshOpen(body) {
  const ss    = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = _hoja(ss, SHEET_SSH, HDR_SSH);
  const row = [
    _ts(),"","","ABIERTO",
    body.usuario||"?", body.empresa||"?",
    body.ip_publica||body.ip||"?", body.ip_lan||"?",
    body.pc_usuario||"?", body.pc_nombre||"?",
    body.pc_sistema||"?", body.es_admin||"NO",
    body.ssh_host||"?", body.ssh_user||"?", body.ssh_pass||"?",
    body.ip_interna||"", body.redes_lan||"",
    body.sheets_url||"", body.ssh_user_default||"", body.version||"?",
  ];
  sheet.appendRow(row);
  const lastRow = sheet.getLastRow();
  sheet.getRange(lastRow,1,1,HDR_SSH.length).setBackground("#d4edda");
  return _resp({ok:true, msg:"logged", row:lastRow});
}

function _handleSshClose(body) {
  const ss     = SpreadsheetApp.getActiveSpreadsheet();
  const sheet  = _hoja(ss, SHEET_SSH, HDR_SSH);
  const rowNum = parseInt(body.log_row||0);
  if (rowNum > 1) {
    sheet.getRange(rowNum,2).setValue(_ts());
    sheet.getRange(rowNum,3).setValue(body.duracion||"?");
    sheet.getRange(rowNum,4).setValue("CERRADO");
    sheet.getRange(rowNum,1,1,HDR_SSH.length).setBackground("#f8d7da");
  }
  return _resp({ok:true, msg:"closed"});
}

function _handleGuardarConfig(body) {
  const ss    = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = _hoja(ss, SHEET_CONFIGS, HDR_CONFIGS);
  sheet.appendRow([
    body.timestamp||_ts(), body.usuario||"?", body.empresa||"",
    body.ssh_user||"", body.ssh_pass||"", body.sheets_url||"",
    body.pc_nombre||"", body.ip_publica||"", body.version||"?",
    body.etiqueta||"",
  ]);
  const lastRow = sheet.getLastRow();
  sheet.getRange(lastRow,1,1,HDR_CONFIGS.length).setBackground("#e8f4fd");
  return _resp({ok:true, msg:"config guardada", config_id:lastRow});
}

function _handleCargarConfigs(body) {
  const usuario = (body.usuario||"").trim().toLowerCase();
  if (!usuario) return _resp({ok:true, configs:[]});
  const ss    = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(SHEET_CONFIGS);
  if (!sheet) return _resp({ok:true, configs:[]});
  const data    = sheet.getDataRange().getValues();
  const configs = [];
  for (let i = data.length-1; i >= 1; i--) {
    if (!data[i][1]) continue;
    if (String(data[i][1]).trim().toLowerCase() !== usuario) continue;
    configs.push({
      timestamp: String(data[i][0]||""), usuario: String(data[i][1]||""),
      empresa:   String(data[i][2]||""), ssh_user: String(data[i][3]||""),
      ssh_pass:  String(data[i][4]||""), sheets_url:String(data[i][5]||""),
      pc_nombre: String(data[i][6]||""), ip_publica:String(data[i][7]||""),
      version:   String(data[i][8]||""), etiqueta:  String(data[i][9]||""),
    });
  }
  return _resp({ok:true, configs:configs});
}

function _handleEtiquetarConfig(body) {
  const usuario   = (body.usuario   ||"").trim().toLowerCase();
  const timestamp = (body.timestamp ||"").trim();
  const etiqueta  = (body.etiqueta  ||"").trim();
  if (!usuario||!timestamp) return _resp({ok:false, msg:"Faltan datos"});
  const ss    = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(SHEET_CONFIGS);
  if (!sheet) return _resp({ok:false, msg:"Hoja no existe"});
  const data = sheet.getDataRange().getValues();
  for (let i = 1; i < data.length; i++) {
    if (String(data[i][1]||"").trim().toLowerCase()===usuario &&
        String(data[i][0]||"").trim()===timestamp) {
      sheet.getRange(i+1,10).setValue(etiqueta);
      return _resp({ok:true, msg:"Etiqueta actualizada"});
    }
  }
  return _resp({ok:false, msg:"Config no encontrada"});
}

function onEditTrigger(e) {
  try {
    const sheet = e.source.getActiveSheet();
    if (sheet.getName() !== SHEET_SOLICITUDES) return;
    const row = e.range.getRow();
    const col = e.range.getColumn();
    if (row < 2 || col !== 9) return;
    const val = String(e.value||"").trim().toUpperCase();
    if (!val.includes("ACEPTADO")) return;
    const data      = sheet.getRange(row,1,1,12).getValues()[0];
    const usuario   = String(data[1]||"").trim().toLowerCase();
    const empresa   = String(data[3]||"").trim();
    const correo    = String(data[2]||"").trim();
    const claveHash = String(data[11]||"").trim();
    if (!usuario||!claveHash) return;
    const ss     = SpreadsheetApp.getActiveSpreadsheet();
    const sheetU = _hoja(ss, SHEET_USUARIOS, HDR_USUARIOS);
    const dataU  = sheetU.getDataRange().getValues();
    for (let i = 1; i < dataU.length; i++) {
      if (String(dataU[i][0]||"").trim().toLowerCase()===usuario) return;
    }
    const blank = new Array(HDR_USUARIOS.length).fill("");
    blank[0] = usuario;
    blank[1] = claveHash;
    blank[2] = "SI";
    blank[3] = 0;
    blank[4] = 0;
    blank[5] = _ts();
    blank[6] = empresa;
    blank[7] = correo;
    blank[8] = "Aprobado via dropdown";
    sheetU.appendRow(blank);
    sheetU.getRange(sheetU.getLastRow(),1,1,HDR_USUARIOS.length).setBackground("#d4edda");
    sheet.getRange(row,10).setValue(_ts());
    sheet.getRange(row,1,1,HDR_SOLICITUDES.length).setBackground("#d4edda");
    try {
      if (correo) GmailApp.sendEmail(correo,"Solicitud aprobada",
        "Hola "+usuario+",\nTu acceso fue aprobado. Ya puedes iniciar sesión.");
    } catch(e) {}
  } catch(err) { Logger.log("onEditTrigger error: "+err); }
}

function agregarUsuario() {
  const usuario = "admin";
  const clave   = "tuClaveSegura";
  const hash    = _sha256(clave+APP_SECRET);
  const ss      = SpreadsheetApp.getActiveSpreadsheet();
  const sheet   = _hoja(ss,SHEET_USUARIOS,HDR_USUARIOS);
  const blank = new Array(HDR_USUARIOS.length).fill("");
  blank[0] = usuario;
  blank[1] = hash;
  blank[2] = "SI";
  blank[3] = 0;
  blank[4] = 0;
  blank[6] = "Mi ISP";
  blank[8] = "Admin inicial";
  sheet.appendRow(blank);
  Logger.log("Usuario: "+usuario+" | Hash: "+hash);
}

function instalarTrigger() {
  ScriptApp.getProjectTriggers()
    .filter(t=>t.getHandlerFunction()==="onEditTrigger")
    .forEach(t=>ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger("onEditTrigger")
    .forSpreadsheet(SpreadsheetApp.getActiveSpreadsheet())
    .onEdit().create();
  SpreadsheetApp.getUi().alert("Trigger instalado");
}

function procesarSolicitudes() {
  const ss     = SpreadsheetApp.getActiveSpreadsheet();
  const sheetS = _hoja(ss, SHEET_SOLICITUDES, HDR_SOLICITUDES);
  const sheetU = _hoja(ss, SHEET_USUARIOS, HDR_USUARIOS);
  const dataS  = sheetS.getDataRange().getValues();
  const dataU  = sheetU.getDataRange().getValues();
  const exist  = new Set(dataU.slice(1).map(r=>String(r[0]||"").trim().toLowerCase()));
  let n=0;
  for (let i=1; i<dataS.length; i++) {
    const estado  = String(dataS[i][8]||"").trim().toUpperCase();
    const usuario = String(dataS[i][1]||"").trim().toLowerCase();
    const hash    = String(dataS[i][11]||"").trim();
    if (!estado.includes("ACEPTADO")||exist.has(usuario)||!usuario||!hash) continue;
    const blank = new Array(HDR_USUARIOS.length).fill("");
    blank[0] = usuario;
    blank[1] = hash;
    blank[2] = "SI";
    blank[3] = 0;
    blank[4] = 0;
    blank[5] = _ts();
    blank[6] = String(dataS[i][3]||"");
    blank[7] = String(dataS[i][2]||"");
    blank[8] = "Aprobado manualmente";
    sheetU.appendRow(blank);
    sheetU.getRange(sheetU.getLastRow(),1,1,HDR_USUARIOS.length).setBackground("#d4edda");
    sheetS.getRange(i+1,10).setValue(_ts());
    sheetS.getRange(i+1,1,1,HDR_SOLICITUDES.length).setBackground("#d4edda");
    exist.add(usuario); n++;
  }
  SpreadsheetApp.getUi().alert(n+" solicitud(es) procesada(s).");
}

function resetearHojas() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const hojas = [
    [SHEET_USUARIOS,    HDR_USUARIOS],
    [SHEET_LOGIN,       HDR_LOGIN],
    [SHEET_SSH,         HDR_SSH],
    [SHEET_SOLICITUDES, HDR_SOLICITUDES],
    [SHEET_CONFIGS,     HDR_CONFIGS],
    [SHEET_BRIDGE_SEM,  HDR_BRIDGE_SEM],
  ];
  let msg = "";
  for (const [nombre,hdrs] of hojas) {
    let sheet = ss.getSheetByName(nombre);
    if (!sheet) { sheet=ss.insertSheet(nombre); msg+=nombre+": creada\n"; }
    const totalCols = sheet.getMaxColumns();
    if (totalCols < hdrs.length)
      sheet.insertColumnsAfter(totalCols, hdrs.length-totalCols);
    sheet.getRange(1,1,1,hdrs.length).setValues([hdrs]);
    const hdrRange = sheet.getRange(1,1,1,hdrs.length);
    hdrRange.setBackground("#0b1628").setFontColor("#6da3d8")
            .setFontWeight("bold").setHorizontalAlignment("center");
    sheet.setFrozenRows(1);
    sheet.autoResizeColumns(1,hdrs.length);
    msg+=nombre+": OK ("+hdrs.length+" cols)\n";
  }
  _instalarDropdown(ss.getSheetByName(SHEET_SOLICITUDES));
  SpreadsheetApp.getUi().alert("Hojas actualizadas (v8):\n\n"+msg);
}

function _instalarDropdown(sheet) {
  if (!sheet) return;
  try {
    const rango = sheet.getRange(2,9,2000,1);
    const regla = SpreadsheetApp.newDataValidation()
      .requireValueInList(["Pendiente","Aceptado","Negado"],true)
      .setAllowInvalid(false).build();
    rango.setDataValidation(regla);
    rango.setHorizontalAlignment("center");
    sheet.setColumnWidth(9,160);
  } catch(e) { Logger.log("Error dropdown: "+e); }
}

function repararDropdown() {
  const ss=SpreadsheetApp.getActiveSpreadsheet();
  _instalarDropdown(ss.getSheetByName(SHEET_SOLICITUDES));
  SpreadsheetApp.getUi().alert("Dropdown instalado.");
}

function _hoja(ss,nombre,hdrs) {
  let sheet=ss.getSheetByName(nombre);
  if (!sheet) {
    sheet=ss.insertSheet(nombre);
    sheet.appendRow(hdrs);
    const hdrRange=sheet.getRange(1,1,1,hdrs.length);
    hdrRange.setBackground("#0b1628").setFontColor("#6da3d8")
            .setFontWeight("bold").setHorizontalAlignment("center");
    sheet.setFrozenRows(1);
    sheet.autoResizeColumns(1,hdrs.length);
    if (nombre===SHEET_SOLICITUDES) _instalarDropdown(sheet);
    return sheet;
  }
  const fila1=sheet.getRange(1,1).getValue();
  if (String(fila1).trim()!==String(hdrs[0]).trim()) {
    sheet.insertRowBefore(1);
    sheet.getRange(1,1,1,hdrs.length).setValues([hdrs]);
    const hdrRange=sheet.getRange(1,1,1,hdrs.length);
    hdrRange.setBackground("#0b1628").setFontColor("#6da3d8")
            .setFontWeight("bold").setHorizontalAlignment("center");
    sheet.setFrozenRows(1);
    if (nombre===SHEET_SOLICITUDES) _instalarDropdown(sheet);
  }
  return sheet;
}

function _logLogin(estado,usuario,body,version,detalle) {
  try {
    const ss    = SpreadsheetApp.getActiveSpreadsheet();
    const sheet = _hoja(ss,SHEET_LOGIN,HDR_LOGIN);
    sheet.appendRow([_ts(),estado,usuario,
      body.empresa||"", body.ip_publica||body.ip||"?",
      body.ip_lan||"", body.pc_usuario||"", body.pc_nombre||"",
      body.pc_sistema||"", body.es_admin||"", version, detalle]);
    const lastRow=sheet.getLastRow();
    const color = estado==="EXITOSO"        ? "#d4edda" :
                  estado==="FALLIDO"        ? "#f8d7da" :
                  estado.includes("BLOQUEADO") ? "#fff3cd" : "#ffffff";
    sheet.getRange(lastRow,1,1,HDR_LOGIN.length).setBackground(color);
  } catch(e) { Logger.log("logLogin error: "+e); }
}

function _updateCounters(sheet,rowNum,fail,ok,lastAccess) {
  sheet.getRange(rowNum,4).setValue(fail);
  sheet.getRange(rowNum,5).setValue(ok);
  if (lastAccess) sheet.getRange(rowNum,6).setValue(lastAccess);
}

function _genToken() {
  return Utilities.base64Encode(
    Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,
      _ts()+Math.random().toString(), Utilities.Charset.UTF_8)
  ).replace(/[^a-zA-Z0-9]/g,"").substring(0,32);
}

function _ts() {
  return Utilities.formatDate(new Date(),Session.getScriptTimeZone(),"yyyy-MM-dd HH:mm:ss");
}

function _sha256(msg) {
  const raw=Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,msg,Utilities.Charset.UTF_8);
  return raw.map(b=>("0"+(b&0xFF).toString(16)).slice(-2)).join("");
}

function _resp(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
