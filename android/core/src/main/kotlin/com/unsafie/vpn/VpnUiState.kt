package com.unsafie.vpn

enum class VpnUiState {
    CONNECTING,
    DISCONNECTING,
    ON,
    OFF,
}

fun vpnUiState(running: Boolean, requested: Boolean?): VpnUiState {
    if (requested != null && requested != running) {
        return if (requested) VpnUiState.CONNECTING else VpnUiState.DISCONNECTING
    }
    return if (running) VpnUiState.ON else VpnUiState.OFF
}

fun vpnUiStateBusy(state: VpnUiState): Boolean = state == VpnUiState.CONNECTING || state == VpnUiState.DISCONNECTING
