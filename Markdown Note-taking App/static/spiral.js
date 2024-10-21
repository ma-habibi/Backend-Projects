// Initialize canvas
let canvas = document.querySelector("canvas");
let ctx = canvas.getContext("2d");
let width = canvas.width = window.innerWidth;
let height = canvas.height = window.innerHeight;

// Map class
class Map {
    constructor(w, h) {
        this.width = w;
        this.height = h;
        this.initAnimation();
    }

    initAnimation() {
        // Initialize variables
        this.maxSpiral = this.height / 1000.0;
        this.dt = 0.005; // Step: tf - ti
        this.amp = 1.0;
        this.rotate = false;
        this.rotated = 0.0;
        this.resizeDir = false;
        this.dResize = 1.0;
        this.dRotate = 0.005;
        this.minResize = this.height / 1000.0;
        this.maxResize = this.height;
    }

    putNextFrameVars() {
        // Stop rotation, start resize
        if (this.rotated >= Math.PI)
            this.rotate = false;

        if (this.rotate) {
            this.rotated += this.dRotate; // Rotate
        } else {
            // Resize
            this.maxSpiral += (this.resizeDir) ? this.dResize : -this.dResize;

            // Set direction
            if (this.maxSpiral >= this.maxResize) {
                this.resizeDir = false;
                this.rotated = 0.0;
                this.rotate = true;
            }
            if (this.maxSpiral <= this.minResize) {
                this.resizeDir = true;
            }
        }
    }

    drawMap(ctx) {
        let t, x_offset, y_offset;

        // Get the spiral in the middle
        x_offset = this.width / 2.0;
        y_offset = this.height / 2.0;

        // Update animation variables
        this.putNextFrameVars();

        // Clear canvas with a fade effect
        ctx.fillStyle = "rgba(0, 0, 0, 0.05)";
        ctx.fillRect(0, 0, this.width, this.height);

        // Set drawing color
        ctx.fillStyle = "#133700";

        // Draw spiral
        for (t = 0.0; t < this.maxSpiral; t += this.dt) {
            ctx.fillRect(
                x_offset + this.amp * (t * Math.cos(t + this.rotated)),
                y_offset + this.amp * (t * Math.sin(t)),
                2, 2
            );
        }
    }
}

// Create map object
let map = new Map(width, height);

function animate() {
    // Redraw the spiral in the next frame
    map.drawMap(ctx);
    requestAnimationFrame(animate);
}

// Start animation loop
animate();

// Reload on window resize
window.addEventListener("resize", () => location.reload());
