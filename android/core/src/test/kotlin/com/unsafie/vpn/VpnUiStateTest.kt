package com.unsafie.vpn

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class VpnUiStateTest {
    @Test
    fun settledStateFollowsTheEngine() {
        assertEquals(VpnUiState.ON, vpnUiState(running = true, requested = null))
        assertEquals(VpnUiState.OFF, vpnUiState(running = false, requested = null))
    }

    @Test
    fun aRequestThatHasNotLandedYetShowsProgress() {
        assertEquals(VpnUiState.CONNECTING, vpnUiState(running = false, requested = true))
        assertEquals(VpnUiState.DISCONNECTING, vpnUiState(running = true, requested = false))
    }

    @Test
    fun aRequestThatLandedIsNoLongerProgress() {
        assertEquals(VpnUiState.ON, vpnUiState(running = true, requested = true))
        assertEquals(VpnUiState.OFF, vpnUiState(running = false, requested = false))
    }

    @Test
    fun busyIsExactlyTheTwoTransitions() {
        assertTrue(vpnUiStateBusy(VpnUiState.CONNECTING))
        assertTrue(vpnUiStateBusy(VpnUiState.DISCONNECTING))
        assertFalse(vpnUiStateBusy(VpnUiState.ON))
        assertFalse(vpnUiStateBusy(VpnUiState.OFF))
    }
}
