package com.unsafie.vpn

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class UpdateTest {
    @Test
    fun releaseCandidateSortsBeforeItsRelease() {
        assertTrue(isNewerVersion("0.4.0-rc1", "0.4.0"))
        assertFalse(isNewerVersion("0.4.0", "0.4.0-rc1"))
    }

    @Test
    fun numbersAreComparedAsNumbers() {
        assertTrue(isNewerVersion("0.9.0", "0.10.0"))
        assertTrue(isNewerVersion("v1.2", "1.2.1"))
        assertFalse(isNewerVersion("1.2.1", "1.2"))
    }

    @Test
    fun sameVersionIsNotNewer() {
        assertFalse(isNewerVersion("1.0.0", "1.0.0"))
        assertEquals(0, compareVersions("1.0.0", "v1.0.0"))
    }

    @Test
    fun abiPicksTheFirstBuiltOne() {
        assertEquals("arm64-v8a", updateAbi(listOf("arm64-v8a", "armeabi-v7a")))
        assertEquals("armeabi-v7a", updateAbi(listOf("armeabi-v7a")))
        assertNull(updateAbi(listOf("x86_64")))
    }

    @Test
    fun urlsJoinWithoutDoubleSlashes() {
        assertEquals(
            "https://example.com/api/v1/update/1.2.3/arm64-v8a",
            updateApkUrl("https://example.com/api/v1/update/", "1.2.3", "arm64-v8a"),
        )
    }

    @Test
    fun updatesNeedBothHalvesOfTheConfiguration() {
        assertTrue(updatesConfigured("https://example.com", "token"))
        assertFalse(updatesConfigured("", "token"))
        assertFalse(updatesConfigured("https://example.com", ""))
    }
}
