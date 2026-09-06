package com.unsafie.vpn

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.VpnService
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.Easing
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.LinearOutSlowInEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PowerSettingsNew
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.State
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.draw.scale
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.delay

private val buttonDiameter = 200.dp
private val iconDiameter = 96.dp

private const val HANDSHAKE_TIMEOUT_MS = 15_000L

private const val RING_COUNT = 3
private const val RING_START = 1.02f
private const val RING_TRAVEL = 0.55f
private const val RING_ALPHA = 0.45f

private const val GLOW_RADIUS = 1.8f
private const val GLOW_ALPHA = 0.10f
private const val GLOW_SWING = 0.08f

private const val SWEEP_RADIUS = 1.1f
private const val SWEEP_ALPHA = 0.85f
private const val SWEEP_DEGREES = 70f

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        setContent {
            UnsafieTheme {
                Scaffold(modifier = Modifier.fillMaxSize()) { innerPadding ->
                    VpnScreen(modifier = Modifier.padding(innerPadding))
                }
            }
        }
    }
}

@Composable
private fun UnsafieTheme(content: @Composable () -> Unit) {
    val context = LocalContext.current
    val dark = isSystemInDarkTheme()
    val scheme: ColorScheme =
        when {
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.S -> {
                if (dark) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
            }

            dark -> {
                darkColorScheme()
            }

            else -> {
                lightColorScheme()
            }
        }
    MaterialTheme(colorScheme = scheme, content = content)
}

@Composable
private fun stateText(state: VpnUiState): String =
    when (state) {
        VpnUiState.CONNECTING -> stringResource(R.string.state_connecting)
        VpnUiState.DISCONNECTING -> stringResource(R.string.state_disconnecting)
        VpnUiState.ON -> stringResource(R.string.state_on)
        VpnUiState.OFF -> stringResource(R.string.state_off)
    }

@Composable
private fun VpnScreen(modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val running by MyVpnService.running.collectAsStateWithLifecycle()

    var requested by remember { mutableStateOf<Boolean?>(null) }
    val uiState = vpnUiState(running = running, requested = requested)
    val busy = vpnUiStateBusy(uiState)

    LaunchedEffect(requested, running) {
        val target = requested ?: return@LaunchedEffect
        if (target != running) {
            delay(HANDSHAKE_TIMEOUT_MS)
        }
        requested = null
    }

    val notificationsLauncher =
        rememberLauncherForActivityResult(
            ActivityResultContracts.RequestPermission(),
        ) { }

    LaunchedEffect(Unit) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            notificationsLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    val consentLauncher =
        rememberLauncherForActivityResult(
            ActivityResultContracts.StartActivityForResult(),
        ) { result ->
            if (result.resultCode == Activity.RESULT_OK) {
                requested = true
                context.sendVpnCommand(null)
            }
        }

    val description = stateText(uiState)

    Box(
        modifier = modifier.fillMaxSize(),
        contentAlignment = Alignment.Center,
    ) {
        PowerHalo(
            active = running,
            busy = busy,
            color = MaterialTheme.colorScheme.primary,
            diameter = buttonDiameter,
            modifier = Modifier.matchParentSize(),
        )
        PowerButton(
            running = running,
            stateText = description,
            onClick = {
                if (running) {
                    requested = false
                    context.sendVpnCommand(MyVpnService.ACTION_STOP)
                } else {
                    val consent = VpnService.prepare(context)
                    if (consent != null) {
                        consentLauncher.launch(consent)
                    } else {
                        requested = true
                        context.sendVpnCommand(null)
                    }
                }
            },
        )
    }
}

@Composable
private fun PowerButton(running: Boolean, stateText: String, onClick: () -> Unit) {
    val haptics = LocalHapticFeedback.current

    val pop = remember { Animatable(1f) }
    var settled by remember { mutableStateOf<Boolean?>(null) }
    LaunchedEffect(running) {
        val previous = settled
        settled = running
        if (previous == null || previous == running) return@LaunchedEffect
        haptics.performHapticFeedback(HapticFeedbackType.LongPress)
        pop.snapTo(1f)
        pop.animateTo(
            targetValue = 1.06f,
            animationSpec = spring(stiffness = Spring.StiffnessHigh),
        )
        pop.animateTo(
            targetValue = 1f,
            animationSpec =
                spring(
                    dampingRatio = Spring.DampingRatioMediumBouncy,
                    stiffness = Spring.StiffnessLow,
                ),
        )
    }

    val interactionSource = remember { MutableInteractionSource() }
    val pressed by interactionSource.collectIsPressedAsState()

    val pressScale by animateFloatAsState(
        targetValue = if (pressed) 0.95f else 1f,
        animationSpec =
            if (pressed) {
                spring(stiffness = Spring.StiffnessHigh)
            } else {
                spring(
                    dampingRatio = Spring.DampingRatioMediumBouncy,
                    stiffness = Spring.StiffnessMedium,
                )
            },
        label = "press",
    )

    val iconRotation by animateFloatAsState(
        targetValue = if (running) 360f else 0f,
        animationSpec = spring(dampingRatio = 0.6f, stiffness = Spring.StiffnessLow),
        label = "rotation",
    )

    val containerColor by animateColorAsState(
        targetValue =
            if (running) {
                MaterialTheme.colorScheme.primary
            } else {
                MaterialTheme.colorScheme.surfaceVariant
            },
        animationSpec = tween(durationMillis = 350, easing = FastOutSlowInEasing),
        label = "container",
    )
    val contentColor by animateColorAsState(
        targetValue =
            if (running) {
                MaterialTheme.colorScheme.onPrimary
            } else {
                MaterialTheme.colorScheme.onSurfaceVariant
            },
        animationSpec = tween(durationMillis = 350, easing = FastOutSlowInEasing),
        label = "content",
    )

    Button(
        onClick = onClick,
        shape = CircleShape,
        colors =
            ButtonDefaults.buttonColors(
                containerColor = containerColor,
                contentColor = contentColor,
            ),
        elevation =
            ButtonDefaults.buttonElevation(
                defaultElevation = 6.dp,
                pressedElevation = 2.dp,
            ),
        contentPadding = PaddingValues(0.dp),
        interactionSource = interactionSource,
        modifier =
            Modifier
                .size(buttonDiameter)
                .scale(pressScale * pop.value)
                .semantics { stateDescription = stateText },
    ) {
        Icon(
            imageVector = Icons.Filled.PowerSettingsNew,
            contentDescription = stringResource(R.string.toggle),
            modifier =
                Modifier
                    .size(iconDiameter)
                    .rotate(iconRotation),
        )
    }
}

@Composable
private fun PowerHalo(active: Boolean, busy: Boolean, color: Color, diameter: Dp, modifier: Modifier = Modifier) {
    val motion = rememberMotionEnabled()

    val activeAlpha =
        animateFloatAsState(
            targetValue = if (active) 1f else 0f,
            animationSpec = tween(durationMillis = 450, easing = LinearOutSlowInEasing),
            label = "haloAlpha",
        )
    val busyAlpha =
        animateFloatAsState(
            targetValue = if (busy) 1f else 0f,
            animationSpec = tween(durationMillis = 220, easing = LinearEasing),
            label = "busyAlpha",
        )

    val pulsing = motion && activeAlpha.value > 0f
    val sweeping = motion && busyAlpha.value > 0f
    val wave = animatedPhase(enabled = pulsing, durationMillis = 2800, label = "wave")
    val sweep = animatedPhase(enabled = sweeping, durationMillis = 1100, label = "sweep")
    val breath =
        animatedPhase(
            enabled = pulsing,
            durationMillis = 2100,
            label = "breath",
            easing = FastOutSlowInEasing,
            repeatMode = RepeatMode.Reverse,
        )

    Canvas(modifier = modifier) {
        val radius = diameter.toPx() / 2f
        if (activeAlpha.value > 0f) {
            drawPulse(
                color = color,
                radius = radius,
                wave = wave.value,
                breath = breath.value,
                alpha = activeAlpha.value,
            )
        }
        if (busyAlpha.value > 0f) {
            drawSweep(
                color = color,
                radius = radius,
                start = sweep.value * 360f,
                alpha = busyAlpha.value,
            )
        }
    }
}

private fun DrawScope.drawPulse(color: Color, radius: Float, wave: Float, breath: Float, alpha: Float) {
    val glowRadius = radius * GLOW_RADIUS
    val glow = (GLOW_ALPHA + GLOW_SWING * breath) * alpha
    drawCircle(
        brush =
            Brush.radialGradient(
                colors = listOf(color.copy(alpha = glow), Color.Transparent),
                center = center,
                radius = glowRadius,
            ),
        radius = glowRadius,
    )
    repeat(RING_COUNT) { index ->
        val progress = (wave + index.toFloat() / RING_COUNT) % 1f
        val fade = (1f - progress) * (1f - progress)
        drawCircle(
            color = color.copy(alpha = fade * RING_ALPHA * alpha),
            radius = radius * (RING_START + RING_TRAVEL * progress),
            style = Stroke(width = 2.dp.toPx()),
        )
    }
}

private fun DrawScope.drawSweep(color: Color, radius: Float, start: Float, alpha: Float) {
    val arcRadius = radius * SWEEP_RADIUS
    drawArc(
        color = color.copy(alpha = SWEEP_ALPHA * alpha),
        startAngle = start,
        sweepAngle = SWEEP_DEGREES,
        useCenter = false,
        topLeft = Offset(center.x - arcRadius, center.y - arcRadius),
        size = Size(arcRadius * 2f, arcRadius * 2f),
        style = Stroke(width = 3.dp.toPx(), cap = StrokeCap.Round),
    )
}

@Composable
private fun animatedPhase(
    enabled: Boolean,
    durationMillis: Int,
    label: String,
    easing: Easing = LinearEasing,
    repeatMode: RepeatMode = RepeatMode.Restart,
): State<Float> {
    if (!enabled) return remember { mutableStateOf(0f) }
    val transition = rememberInfiniteTransition(label = label)
    return transition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec =
            infiniteRepeatable(
                animation = tween(durationMillis, easing = easing),
                repeatMode = repeatMode,
            ),
        label = label,
    )
}

@Composable
private fun rememberMotionEnabled(): Boolean {
    val context = LocalContext.current
    return remember(context) {
        Settings.Global.getFloat(
            context.contentResolver,
            Settings.Global.ANIMATOR_DURATION_SCALE,
            1f,
        ) > 0f
    }
}

private fun Context.sendVpnCommand(action: String?) {
    val intent = Intent(this, MyVpnService::class.java).also { it.action = action }
    startForegroundService(intent)
}
