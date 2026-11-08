// A glow around the Earth: a slightly larger shell, added on top, brightest just outside
// the planet's edge and fading out into space, stronger on the sunlit side.
Shader "Matchmaker/Atmosphere"
{
    Properties
    {
        _Color ("Glow", Color) = (0.45, 0.65, 1.0, 1)
        _SunDir ("Direction to the sun (world)", Vector) = (-0.6, 0.35, -0.7, 0)
        _Strength ("Strength", Float) = 1.4
    }
    SubShader
    {
        Tags { "RenderType"="Transparent" "Queue"="Transparent" "RenderPipeline"="UniversalPipeline" }
        Pass
        {
            Name "Atmosphere"
            Tags { "LightMode"="UniversalForward" }
            Blend One One
            ZWrite Off
            Cull Back
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"

            CBUFFER_START(UnityPerMaterial)
                float4 _Color;
                float4 _SunDir;
                float _Strength;
            CBUFFER_END

            struct Attributes { float4 positionOS : POSITION; float3 normalOS : NORMAL; };
            struct Varyings { float4 positionCS : SV_POSITION; float3 normalWS : TEXCOORD0; float3 positionWS : TEXCOORD1; };

            Varyings vert(Attributes i)
            {
                Varyings o;
                VertexPositionInputs p = GetVertexPositionInputs(i.positionOS.xyz);
                o.positionCS = p.positionCS;
                o.positionWS = p.positionWS;
                o.normalWS = TransformObjectToWorldNormal(i.normalOS);
                return o;
            }

            half4 frag(Varyings i) : SV_Target
            {
                float3 N = normalize(i.normalWS);
                float3 V = normalize(GetWorldSpaceViewDir(i.positionWS));
                float rim = saturate(dot(N, V));
                // Zero at the shell's own silhouette, peaking just inside it (the planet's
                // limb), zero again over the planet's face.
                float glow = smoothstep(0.0, 0.32, rim) * pow(1.0 - rim, 3.0);
                float sun = saturate(dot(N, normalize(_SunDir.xyz)) + 0.35);
                return half4(_Color.rgb * glow * sun * _Strength, 1.0);
            }
            ENDHLSL
        }
    }
}
